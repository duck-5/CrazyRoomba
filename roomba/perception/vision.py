"""
Integrated Camera, Multi-Object (Person, Cat, Pet, Obstacles) Vision Service for Roomba 960 (Raspberry Pi 5).
Provides:
- Resilient camera initialization (never crashes if camera or OpenCV is missing)
- Multi-class object detection (COCO 80 classes via YOLOX ONNX, Pascal VOC 20 classes via MobileNet-SSD, and HOG fallback)
- Specialized tracking for humans (person) and pets (cat, dog) with configurable target selector
- Proactive obstacle detection for physical AI navigation
- Live annotated MJPEG frame generation for Web Cockpit
- Automatic perception injection into RobotController for FollowPersonMode, PetCompanionMode, and WanderMode
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
import urllib.request
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

from roomba.perception.camera import (
    BaseCameraSource,
    OpenCVCameraSource,
    MockCameraSource,
    Picamera2CameraSource,
    LibcameraCLISource,
    discover_video_devices,
)
from roomba.perception.classes import (
    COCO_CLASSES,
    VOC_CLASSES,
    get_color_for_label,
    nms_boxes,
)
from roomba.config import config, BASE_DIR

_YOLOX_MODEL_URL = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/object_detection_yolox/object_detection_yolox_2022nov.onnx"
_YOLOX_FILENAME = "object_detection_yolox_2022nov.onnx"
_MOBILENET_PROTOTXT_URL = "https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/voc/MobileNetSSD_deploy.prototxt"
_MOBILENET_MODEL_URL = "https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/mobilenet_iter_73000.caffemodel"
_MOBILENET_PERSON_CLASS_ID = 15
_MOBILENET_CAT_CLASS_ID = 8

logger = logging.getLogger("roomba.perception.vision")


class VisionService:
    """Manages camera capture, multi-object AI detection (people, cats, obstacles), and MJPEG preview frames."""

    def __init__(self, controller: Any = None, device_index: Optional[int] = None):
        self.controller = controller
        self.device_index: int = config.camera_device_index if device_index is None else device_index
        self.device_path: Optional[str] = None
        self.camera_backend: str = "none"
        self.rotation: int = config.camera_rotation % 360

        self.camera: Optional[BaseCameraSource] = None
        self.is_mock: bool = False
        self.available: bool = False
        self.status: str = "uninitialized"  # "uninitialized" | "connected" | "mock" | "error"
        self.error: Optional[str] = None
        self.detector_backend: str = "none"  # "yolox-coco" | "mobilenet-ssd" | "hog" | "mock" | "none"

        # Active tracking target: "person", "cat", "dog", "any"
        self.target_class: str = getattr(config, "vision_target_class", "person")
        self.person_detected: bool = False
        self.target_person: Optional[Dict[str, Any]] = None
        self.cat_detected: bool = False
        self.target_cat: Optional[Dict[str, Any]] = None
        self.dog_detected: bool = False
        self.target_dog: Optional[Dict[str, Any]] = None
        self.target_object: Optional[Dict[str, Any]] = None
        self.detected_objects: List[Dict[str, Any]] = []

        self.last_raw_confidence: float = 0.0
        self.fps: float = 0.0
        self.frame_count: int = 0
        self.last_frame_time: float = 0.0

        self._latest_jpeg: Optional[bytes] = None
        self._frame_event: Optional[asyncio.Event] = None
        self._loop_task: Optional[asyncio.Task] = None
        self._yolox_net: Any = None
        self._yolox_grids: Any = None
        self._yolox_strides: Any = None
        self._last_detected_objects: List[Dict[str, Any]] = []
        self._det_frame_idx: int = 0
        self._ssd_net: Any = None
        self._hog: Any = None
        self._cv2: Any = None
        self._consecutive_failures: int = 0

    def set_target_class(self, target_class: str) -> str:
        """Set active tracking target class ('person', 'cat', 'dog', or 'any')."""
        self.target_class = target_class.lower().strip()
        logger.info(f"Vision target class set to: {self.target_class}")
        return self.target_class

    def get_status(self) -> Dict[str, Any]:
        """Return current camera & multi-object vision status dictionary."""
        return {
            "available": self.available,
            "status": self.status,
            "is_mock": self.is_mock,
            "device_index": self.device_index,
            "device_path": self.device_path,
            "camera_backend": self.camera_backend,
            "rotation": self.rotation,
            "detector_backend": self.detector_backend,
            "target_class": self.target_class,
            "error": self.error,
            "person_detected": self.person_detected,
            "target_person": self.target_person,
            "cat_detected": self.cat_detected,
            "target_cat": self.target_cat,
            "dog_detected": self.dog_detected,
            "target_dog": self.target_dog,
            "target_object": self.target_object,
            "detected_objects": self.detected_objects,
            "last_raw_confidence": round(self.last_raw_confidence, 3),
            "fps": round(self.fps, 1),
            "frame_count": self.frame_count,
            "devices": discover_video_devices(),
        }

    async def initialize(
        self,
        mock: bool = False,
        device_index: Optional[int] = None,
        device_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Safely initialize camera and multi-object detector.
        Never raises on missing hardware or missing OpenCV; records error state instead.
        """
        await self.stop()

        if device_index is not None:
            self.device_index = device_index
        self.device_path = device_path
        self.camera_backend = "none"

        self.is_mock = mock
        self.error = None
        self.person_detected = False
        self.target_person = None
        self.cat_detected = False
        self.target_cat = None
        self.dog_detected = False
        self.target_dog = None
        self.target_object = None
        self.detected_objects = []
        self._consecutive_failures = 0

        if self._frame_event is None:
            self._frame_event = asyncio.Event()

        if mock:
            self.camera = MockCameraSource(device_index=self.device_index)
            await self.camera.open()
            try:
                import cv2
                self._cv2 = cv2
            except Exception as e:
                logger.debug(f"cv2 unavailable in mock camera mode: {e}")
                self._cv2 = None
            self.available = True
            self.status = "mock"
            self.camera_backend = "mock"
            self.detector_backend = "mock"
            self.error = None
            self._start_loop()
            if self.controller:
                self.controller.log_event("info", "Camera Vision initialized in Mock Simulation mode")
            return self.get_status()

        # Real hardware camera path
        try:
            import cv2
            self._cv2 = cv2
        except Exception as e:
            self.available = False
            self.status = "error"
            self.detector_backend = "none"
            self.error = f"OpenCV (cv2) unavailable: {e}"
            logger.warning(self.error)
            if self.controller:
                self.controller.log_event("warn", f"Camera unavailable: {self.error}")
            return self.get_status()

        # Try 1: OpenCV V4L2 (auto-scans /dev/video* and skips Pi ISP/codec nodes)
        # Try 2: Picamera2 (Pi 5 CSI camera native Python bindings)
        # Try 3: rpicam-vid / libcamera-vid MJPEG stream (Pi 5 CSI CLI fallback)
        candidates = [
            OpenCVCameraSource(
                device_index=self.device_index,
                width=640,
                height=480,
                device_path=device_path,
                auto_scan=(device_path is None),
            ),
            Picamera2CameraSource(device_index=self.device_index, width=640, height=480),
            LibcameraCLISource(device_index=self.device_index, width=640, height=480),
        ]

        cam: Optional[BaseCameraSource] = None
        for candidate in candidates:
            try:
                if await candidate.open():
                    cam = candidate
                    break
            except Exception as e:
                logger.debug(f"Camera candidate {candidate.__class__.__name__} failed: {e}")

        if cam is None:
            self.camera = None
            self.available = False
            self.status = "error"
            self.detector_backend = "none"
            discovered = discover_video_devices()
            libcamera_err = getattr(candidates[2], "last_error", None)
            if discovered:
                names = ", ".join(f"{d['path']}({d['name']})" for d in discovered[:6])
                only_internal = all(d["is_pi_internal"] for d in discovered)
                if only_internal and LibcameraCLISource.find_cli() is None:
                    self.error = (
                        f"Only Pi internal ISP/CSI nodes found ({names}), and rpicam-vid/picamera2 "
                        "is unavailable inside this environment. Install rpicam-apps/libcamera or connect a USB webcam, then click Try Again."
                    )
                elif libcamera_err:
                    self.error = (
                        f"Camera devices found ({names}); {libcamera_err}. Click Try Again."
                    )
                else:
                    self.error = (
                        f"Camera devices found ({names}) but none produced frames. "
                        "Ensure no other app holds the camera, then click Try Again."
                    )
            else:
                self.error = (
                    f"No camera detected (index={self.device_index}, no /dev/video* nodes). "
                    "Connect USB/Pi camera and click Try Again."
                )
            logger.warning(self.error)
            if self.controller:
                self.controller.log_event("warn", self.error)
            return self.get_status()

        # Update resolved device index/path/backend
        self.device_index = cam.device_index
        self.device_path = cam.device_path
        self.camera_backend = cam.backend_name

        # Initialize detector (YOLOX COCO primary, MobileNet-SSD secondary, HOG fallback)
        await asyncio.get_running_loop().run_in_executor(None, self._init_detector_sync, cv2)

        self.camera = cam
        self.available = True
        self.status = "connected"
        self.error = None
        self._start_loop()
        if self.controller:
            self.controller.log_event(
                "success",
                f"Camera connected ({self.camera_backend}, {self.device_path or self.device_index}, detector={self.detector_backend})",
            )
        return self.get_status()

    async def retry(
        self,
        mock: bool = False,
        device_index: Optional[int] = None,
        device_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Re-probe and attempt to initialize the camera."""
        return await self.initialize(mock=mock, device_index=device_index, device_path=device_path)

    def _start_loop(self) -> None:
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.create_task(self._vision_loop())

    async def stop(self) -> None:
        """Stop background vision loop and release camera."""
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        self._loop_task = None

        if self.camera is not None:
            try:
                await self.camera.close()
            except Exception as e:
                logger.debug(f"Camera close warning: {e}")
            self.camera = None

        self.available = False
        if self.status != "error":
            self.status = "uninitialized"

    def get_latest_jpeg(self) -> Optional[bytes]:
        """Return latest JPEG-encoded frame bytes, if available."""
        return self._latest_jpeg

    async def wait_next_jpeg(self, last_seq: int, timeout: float = 0.5) -> Tuple[int, Optional[bytes]]:
        """Wait until a newer JPEG frame is available (or timeout), returning (seq, jpeg)."""
        if self.frame_count > last_seq and self._latest_jpeg is not None:
            return self.frame_count, self._latest_jpeg
        if self._frame_event is not None:
            try:
                await asyncio.wait_for(self._frame_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass
        return self.frame_count, self._latest_jpeg

    def set_rotation(self, rotation: int) -> int:
        """Set camera rotation angle in degrees (0, 90, 180, 270)."""
        normalized = (int(rotation) // 90 * 90) % 360
        self.rotation = normalized
        return self.rotation

    def _resolve_yolox_path(self) -> Optional[Path]:
        """Locate or download OpenCV Zoo YOLOX COCO ONNX model."""
        search_dirs = [
            Path("/app/models"),
            BASE_DIR / "models",
            Path.home() / ".cache" / "roomba" / "models",
        ]
        for d in search_dirs:
            model = d / _YOLOX_FILENAME
            if model.exists() and model.stat().st_size > 5_000_000:
                return model

        cache_dir = Path.home() / ".cache" / "roomba" / "models"
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            model = cache_dir / _YOLOX_FILENAME
            logger.info(f"Downloading {_YOLOX_FILENAME} (~35MB)...")
            urllib.request.urlretrieve(_YOLOX_MODEL_URL, str(model))
            if model.exists() and model.stat().st_size > 5_000_000:
                return model
        except Exception as e:
            logger.warning(f"Could not download YOLOX model: {e}")
        return None

    def _init_yolox_anchors(self) -> None:
        """Precompute YOLOX 640x640 anchor grids and strides."""
        import numpy as np
        grids = []
        strides_list = []
        for stride in (8, 16, 32):
            size = 640 // stride
            xv, yv = np.meshgrid(np.arange(size), np.arange(size))
            grid = np.stack((xv, yv), 2).reshape(-1, 2)
            grids.append(grid)
            strides_list.append(np.full((grid.shape[0], 1), stride, dtype=np.float32))
        self._yolox_grids = np.concatenate(grids, axis=0).astype(np.float32)
        self._yolox_strides = np.concatenate(strides_list, axis=0).astype(np.float32)

    def _resolve_mobilenet_paths(self) -> Optional[Tuple[Path, Path]]:
        """Locate or download MobileNet-SSD prototxt and caffemodel."""
        search_dirs = [
            Path("/app/models"),
            BASE_DIR / "models",
            Path.home() / ".cache" / "roomba" / "models",
        ]
        for d in search_dirs:
            proto = d / "MobileNetSSD_deploy.prototxt"
            model = d / "mobilenet_iter_73000.caffemodel"
            if proto.exists() and model.exists() and model.stat().st_size > 1_000_000:
                return proto, model

        cache_dir = Path.home() / ".cache" / "roomba" / "models"
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            proto = cache_dir / "MobileNetSSD_deploy.prototxt"
            model = cache_dir / "mobilenet_iter_73000.caffemodel"
            if not proto.exists():
                logger.info("Downloading MobileNetSSD_deploy.prototxt...")
                urllib.request.urlretrieve(_MOBILENET_PROTOTXT_URL, str(proto))
                txt = proto.read_text(encoding="utf-8", errors="ignore")
                if "confidence_threshold: 0.25" in txt:
                    proto.write_text(txt.replace("confidence_threshold: 0.25", "confidence_threshold: 0.05"), encoding="utf-8")
            if not model.exists() or model.stat().st_size < 1_000_000:
                logger.info("Downloading mobilenet_iter_73000.caffemodel (~23MB)...")
                urllib.request.urlretrieve(_MOBILENET_MODEL_URL, str(model))
            return proto, model
        except Exception as e:
            logger.warning(f"Could not download MobileNet-SSD model: {e}")
            return None

    def _init_detector_sync(self, cv2: Any) -> None:
        """Initialize YOLOX COCO ONNX (primary), MobileNet-SSD (fallback), or HOG."""
        self._yolox_net = None
        self._ssd_net = None
        self._hog = None
        self._last_detected_objects = []
        self._det_frame_idx = 0
        self.detector_backend = "none"

        yolox_path = self._resolve_yolox_path()
        if yolox_path is not None:
            try:
                net = cv2.dnn.readNet(str(yolox_path))
                net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
                net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
                self._init_yolox_anchors()
                self._yolox_net = net
                self.detector_backend = "yolox-coco"
                logger.info(f"Detector initialized: YOLOX COCO 80-Class ({yolox_path})")
                return
            except Exception as e:
                logger.warning(f"YOLOX load failed, falling back to MobileNet-SSD: {e}")

        paths = self._resolve_mobilenet_paths()
        if paths is not None:
            proto, model = paths
            try:
                net = cv2.dnn.readNetFromCaffe(str(proto), str(model))
                self._ssd_net = net
                self.detector_backend = "mobilenet-ssd"
                logger.info(f"Detector initialized: MobileNet-SSD 21-Class ({model})")
                return
            except Exception as e:
                logger.warning(f"MobileNet-SSD load failed, falling back to HOG: {e}")

        try:
            hog = cv2.HOGDescriptor()
            hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
            self._hog = hog
            self.detector_backend = "hog"
            logger.info("Detector initialized: OpenCV HOG (person fallback)")
        except Exception as e:
            logger.warning(f"HOG detector init failed: {e}")
            self._hog = None
            self.detector_backend = "none"

    def _process_real_frame_sync(self, frame: Any) -> Tuple[Optional[Dict[str, Any]], Optional[bytes]]:
        """Run rotation, multi-object AI inference (person, cat, obstacles), and draw colored HUD on frame."""
        cv2 = self._cv2
        if cv2 is None or frame is None:
            return None, None

        if self.rotation == 90:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif self.rotation == 180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        elif self.rotation == 270:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

        h, w = frame.shape[:2]
        detected_objects: List[Dict[str, Any]] = []
        raw_best_person_conf = 0.0

        if self._yolox_net is not None:
            run_infer = (self._det_frame_idx % 2 == 0)
            self._det_frame_idx += 1
            if run_infer:
                import numpy as np
                padded = np.ones((640, 640, 3), dtype=np.float32) * 114.0
                ratio = min(640.0 / float(h), 640.0 / float(w))
                new_w = max(1, int(w * ratio))
                new_h = max(1, int(h * ratio))
                resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR).astype(np.float32)
                padded[:new_h, :new_w] = resized
                blob = np.transpose(padded, (2, 0, 1))[np.newaxis, :, :, :]

                self._yolox_net.setInput(blob)
                outs = self._yolox_net.forward(self._yolox_net.getUnconnectedOutLayersNames())
                dets = outs[0][0].copy()  # (8400, 85)
                dets[:, :2] = (dets[:, :2] + self._yolox_grids) * self._yolox_strides
                dets[:, 2:4] = np.exp(dets[:, 2:4]) * self._yolox_strides

                obj_conf = dets[:, 4]
                # cls_scores shape (8400, 80)
                cls_scores = dets[:, 5:85] * obj_conf[:, np.newaxis]

                # COCO class 0 = person
                person_scores = cls_scores[:, 0]
                raw_best_person_conf = float(np.max(person_scores)) if person_scores.size > 0 else 0.0
                raw_best_person_conf = min(1.0, max(0.0, raw_best_person_conf))

                # Multi-class detection candidates across all 80 classes
                max_cls_indices = np.argmax(cls_scores, axis=1)
                max_cls_scores = np.max(cls_scores, axis=1)
                valid_mask = max_cls_scores > 0.20
                cand_anchors = np.where(valid_mask)[0]

                cand_boxes: List[Tuple[int, int, int, int]] = []
                cand_scores_list: List[float] = []
                cand_class_ids: List[int] = []

                if cand_anchors.size > 0:
                    for a_idx in cand_anchors:
                        cls_idx = int(max_cls_indices[a_idx])
                        score_val = float(max_cls_scores[a_idx])
                        cx, cy, bw_box, bh_box = dets[a_idx, :4]
                        x1 = max(0, int((cx - bw_box / 2.0) / ratio))
                        y1 = max(0, int((cy - bh_box / 2.0) / ratio))
                        x2 = min(w, int((cx + bw_box / 2.0) / ratio))
                        y2 = min(h, int((cy + bh_box / 2.0) / ratio))
                        box_w = x2 - x1
                        box_h = y2 - y1
                        if box_w >= 6 and box_h >= 6:
                            cand_boxes.append((x1, y1, box_w, box_h))
                            cand_scores_list.append(score_val)
                            cand_class_ids.append(cls_idx)

                # Per-class NMS suppression to eliminate redundant boxes without suppressing distinct categories
                keep = nms_boxes(cand_boxes, cand_scores_list, iou_threshold=0.45, class_ids=cand_class_ids)
                for k in keep[:10]:
                    cls_id = cand_class_ids[k]
                    label = COCO_CLASSES[cls_id] if cls_id < len(COCO_CLASSES) else f"class_{cls_id}"
                    bx, by, bw_b, bh_b = cand_boxes[k]
                    conf = cand_scores_list[k]
                    detected_objects.append({
                        "class_id": cls_id,
                        "label": label,
                        "confidence": round(conf, 3),
                        "bbox": [bx, by, bw_b, bh_b],
                        "x_center": round((bx + bw_b / 2.0) / float(w), 4),
                        "bbox_width": round(bw_b / float(w), 4),
                    })

                self._last_detected_objects = detected_objects
            else:
                detected_objects = self._last_detected_objects
                raw_best_person_conf = self.last_raw_confidence

        elif self._ssd_net is not None:
            raw_best_person_conf = 0.0
            resized = cv2.resize(frame, (300, 300))
            blob = cv2.dnn.blobFromImage(resized, 0.007843, (300, 300), 127.5)
            self._ssd_net.setInput(blob)
            detections = self._ssd_net.forward()
            num_det = detections.shape[2] if len(detections.shape) >= 3 else 0

            cand_boxes = []
            cand_scores_list = []
            cand_class_ids = []

            for i in range(num_det):
                conf = float(detections[0, 0, i, 2])
                class_id = int(detections[0, 0, i, 1])
                if class_id == _MOBILENET_PERSON_CLASS_ID and conf > raw_best_person_conf:
                    raw_best_person_conf = conf

                if conf > 0.15 and 0 < class_id < len(VOC_CLASSES):
                    x1 = max(0, int(detections[0, 0, i, 3] * w))
                    y1 = max(0, int(detections[0, 0, i, 4] * h))
                    x2 = min(w, int(detections[0, 0, i, 5] * w))
                    y2 = min(h, int(detections[0, 0, i, 6] * h))
                    box_w = x2 - x1
                    box_h = y2 - y1
                    if box_w >= 6 and box_h >= 6:
                        cand_boxes.append((x1, y1, box_w, box_h))
                        cand_scores_list.append(conf)
                        cand_class_ids.append(class_id)

            # Per-class NMS suppression
            keep = nms_boxes(cand_boxes, cand_scores_list, iou_threshold=0.45, class_ids=cand_class_ids)
            for k in keep[:10]:
                cls_id = cand_class_ids[k]
                label = VOC_CLASSES[cls_id] if cls_id < len(VOC_CLASSES) else f"class_{cls_id}"
                bx, by, bw_b, bh_b = cand_boxes[k]
                conf = cand_scores_list[k]
                detected_objects.append({
                    "class_id": cls_id,
                    "label": label,
                    "confidence": round(conf, 3),
                    "bbox": [bx, by, bw_b, bh_b],
                    "x_center": round((bx + bw_b / 2.0) / float(w), 4),
                    "bbox_width": round(bw_b / float(w), 4),
                })

        elif self._hog is not None:
            raw_best_person_conf = 0.0
            target_w = 320
            scale = target_w / float(w)
            target_h = max(1, int(h * scale))
            small = cv2.resize(frame, (target_w, target_h))

            rects, weights = self._hog.detectMultiScale(
                small,
                winStride=(8, 8),
                padding=(4, 4),
                scale=1.08,
            )

            cand_boxes = []
            cand_scores_list = []
            for idx, (rx, ry, rw, rh) in enumerate(rects):
                if idx < len(weights):
                    raw_w = weights[idx]
                    weight = float(raw_w.item()) if hasattr(raw_w, "item") else float(raw_w)
                else:
                    weight = 0.5
                conf = min(1.0, max(0.0, weight / 1.5))
                if conf > raw_best_person_conf:
                    raw_best_person_conf = conf
                if conf > 0.20:
                    cand_boxes.append((int(rx / scale), int(ry / scale), int(rw / scale), int(rh / scale)))
                    cand_scores_list.append(conf)

            keep = nms_boxes(cand_boxes, cand_scores_list, iou_threshold=0.45)
            for k in keep[:5]:
                bx, by, bw_b, bh_b = cand_boxes[k]
                conf = cand_scores_list[k]
                detected_objects.append({
                    "class_id": 0,
                    "label": "person",
                    "confidence": round(conf, 3),
                    "bbox": [bx, by, bw_b, bh_b],
                    "x_center": round((bx + bw_b / 2.0) / float(w), 4),
                    "bbox_width": round(bw_b / float(w), 4),
                })

        self.last_raw_confidence = raw_best_person_conf
        self.detected_objects = detected_objects

        # Resolve person, cat, dog, and active target objects
        target_person = None
        target_cat = None
        target_dog = None

        persons = [o for o in detected_objects if o["label"] == "person"]
        if persons:
            target_person = max(persons, key=lambda o: o["confidence"])
            self.person_detected = True
        else:
            self.person_detected = False
        self.target_person = target_person

        cats = [o for o in detected_objects if o["label"] == "cat"]
        if cats:
            target_cat = max(cats, key=lambda o: o["confidence"])
            self.cat_detected = True
        else:
            self.cat_detected = False
        self.target_cat = target_cat

        dogs = [o for o in detected_objects if o["label"] == "dog"]
        if dogs:
            target_dog = max(dogs, key=lambda o: o["confidence"])
            self.dog_detected = True
        else:
            self.dog_detected = False
        self.target_dog = target_dog

        if self.target_class == "cat":
            target_object = target_cat
        elif self.target_class == "dog":
            target_object = target_dog
        elif self.target_class == "any":
            target_object = max(detected_objects, key=lambda o: o["confidence"]) if detected_objects else None
        else:
            # Default person target
            target_object = target_person

        self.target_object = target_object

        # Draw category-colored bounding boxes and overlays on frame
        for obj in detected_objects:
            bx, by, bw_b, bh_b = obj["bbox"]
            lbl = obj["label"]
            conf = obj["confidence"]
            color = get_color_for_label(lbl)

            cv2.rectangle(frame, (bx, by), (bx + bw_b, by + bh_b), color, 2)
            caption = f"{lbl.upper()} {int(conf * 100)}%"
            cv2.putText(
                frame,
                caption,
                (bx, max(18, by - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.52,
                color,
                2,
            )

        # Draw HUD status bar
        active_mode = self.controller.mode_manager.active_name if self.controller else "manual"
        mode_text = f"MODE: {active_mode.upper()}"
        summary_parts = []
        if self.cat_detected and self.target_cat:
            summary_parts.append(f"CAT {int(self.target_cat['confidence']*100)}%")
        if self.dog_detected and self.target_dog:
            summary_parts.append(f"DOG {int(self.target_dog['confidence']*100)}%")
        if self.person_detected and self.target_person:
            summary_parts.append(f"PERSON {int(self.target_person['confidence']*100)}%")
        summary_str = f" | {', '.join(summary_parts)}" if summary_parts else ""

        cv2.putText(
            frame,
            f"{mode_text} | {self.fps:.1f} FPS | {self.detector_backend}{summary_str}",
            (10, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.50,
            (255, 255, 255),
            1,
        )

        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
        jpeg = buf.tobytes() if ok else None

        # Return target_person (or active target_object) for backward-compatible signature
        return (target_person if self.target_class == "person" else (target_object or target_person)), jpeg

    def _generate_mock_frame_sync(self, t: float) -> Tuple[Dict[str, Any], Optional[bytes]]:
        """Generate a synthetic camera frame with moving simulated person, cat, and HUD."""
        # Simulated person (upper-body walking)
        person_x = 0.5 + 0.25 * math.sin(t * 0.8)
        person_w = 0.30 + 0.05 * math.cos(t * 0.5)
        sim_person = {
            "class_id": 0,
            "label": "person",
            "confidence": 0.92,
            "x_center": round(person_x, 4),
            "bbox_width": round(person_w, 4),
            "bbox": [int(max(0, (person_x - person_w / 2.0) * 320)), 20, int(person_w * 320), 160],
        }

        # Simulated cat (walking closer to floor)
        cat_x = 0.45 + 0.20 * math.cos(t * 0.6)
        cat_w = 0.22 + 0.03 * math.sin(t * 0.4)
        sim_cat = {
            "class_id": 15,
            "label": "cat",
            "confidence": 0.89,
            "x_center": round(cat_x, 4),
            "bbox_width": round(cat_w, 4),
            "bbox": [int(max(0, (cat_x - cat_w / 2.0) * 320)), 140, int(cat_w * 320), 75],
        }

        # Simulated dog (playful puppy walking in foreground)
        dog_x = 0.30 + 0.18 * math.sin(t * 0.5)
        dog_w = 0.25 + 0.04 * math.cos(t * 0.3)
        sim_dog = {
            "class_id": 16,
            "label": "dog",
            "confidence": 0.86,
            "x_center": round(dog_x, 4),
            "bbox_width": round(dog_w, 4),
            "bbox": [int(max(0, (dog_x - dog_w / 2.0) * 320)), 120, int(dog_w * 320), 80],
        }

        self.detected_objects = [sim_person, sim_cat, sim_dog]
        self.person_detected = True
        self.target_person = sim_person
        self.cat_detected = True
        self.target_cat = sim_cat
        self.dog_detected = True
        self.target_dog = sim_dog
        self.last_raw_confidence = 0.92

        if self.target_class == "cat":
            self.target_object = sim_cat
            active_target = sim_cat
        elif self.target_class == "dog":
            self.target_object = sim_dog
            active_target = sim_dog
        elif self.target_class == "any":
            self.target_object = sim_cat
            active_target = sim_cat
        else:
            self.target_object = sim_person
            active_target = sim_person

        jpeg = None
        if self._cv2 is not None:
            import numpy as np
            cv2 = self._cv2
            w, h = 320, 240
            frame = np.zeros((h, w, 3), dtype=np.uint8)
            frame[:] = (18, 22, 30)

            # Grid lines
            for gx in range(0, w, 40):
                cv2.line(frame, (gx, 0), (gx, h), (30, 38, 52), 1)
            for gy in range(0, h, 40):
                cv2.line(frame, (0, gy), (w, gy), (30, 38, 52), 1)

            # Draw Person (Green)
            pbx, pby, pbw, pbh = sim_person["bbox"]
            cv2.rectangle(frame, (pbx, pby), (min(w - 1, pbx + pbw), min(h - 1, pby + pbh)), (0, 230, 118), 2)
            cv2.circle(frame, (pbx + pbw // 2, pby + 20), 14, (0, 230, 118), 2)
            cv2.putText(frame, "PERSON 92%", (pbx, max(16, pby - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 230, 118), 1)

            # Draw Cat (Amber / Orange) with little cat ears
            cbx, cby, cbw, cbh = sim_cat["bbox"]
            cv2.rectangle(frame, (cbx, cby), (min(w - 1, cbx + cbw), min(h - 1, cby + cbh)), (0, 165, 255), 2)
            # Cat ear triangles
            cv2.line(frame, (cbx + 8, cby), (cbx + 14, cby - 8), (0, 165, 255), 2)
            cv2.line(frame, (cbx + 14, cby - 8), (cbx + 20, cby), (0, 165, 255), 2)
            cv2.line(frame, (cbx + cbw - 20, cby), (cbx + cbw - 14, cby - 8), (0, 165, 255), 2)
            cv2.line(frame, (cbx + cbw - 14, cby - 8), (cbx + cbw - 8, cby), (0, 165, 255), 2)
            cv2.putText(frame, "CAT 89%", (cbx, max(16, cby - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 165, 255), 1)

            # Draw Dog (Warm Sky Blue)
            dbx, dby, dbw, dbh = sim_dog["bbox"]
            cv2.rectangle(frame, (dbx, dby), (min(w - 1, dbx + dbw), min(h - 1, dby + dbh)), (255, 178, 50), 2)
            cv2.putText(frame, "DOG 86%", (dbx, max(16, dby - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (255, 178, 50), 1)

            cv2.putText(frame, "MOCK PHYSICAL AI SIM", (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (180, 200, 220), 1)

            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
            if ok:
                jpeg = buf.tobytes()

        return active_target, jpeg

    async def _vision_loop(self) -> None:
        """Background loop reading frames, detecting multi-class objects, and updating controller perception."""
        loop = asyncio.get_running_loop()
        last_rate_log = 0.0
        while self.available and self.camera is not None:
            t_start = time.monotonic()
            try:
                if self.is_mock:
                    active_target, jpeg = await loop.run_in_executor(None, self._generate_mock_frame_sync, t_start)
                    if jpeg is not None:
                        self._latest_jpeg = jpeg
                    if self.controller:
                        self.controller.set_perception_target({
                            "target_person": self.target_person,
                            "target_cat": self.target_cat,
                            "target_dog": self.target_dog,
                            "target_object": self.target_object,
                            "detected_objects": self.detected_objects,
                            "person_detected": self.person_detected,
                            "cat_detected": self.cat_detected,
                            "dog_detected": self.dog_detected,
                        })
                    self.frame_count += 1
                    self._consecutive_failures = 0
                else:
                    frame = await self.camera.read_frame()
                    if frame is None:
                        self._consecutive_failures += 1
                        if self._consecutive_failures >= 15:
                            self.error = "Camera stopped returning frames. Check connection and click Try Again."
                            self.status = "error"
                            self.available = False
                            if self.controller:
                                self.controller.log_event("error", self.error)
                            await self.camera.close()
                            self.camera = None
                            break
                        await asyncio.sleep(0.1)
                        continue

                    self._consecutive_failures = 0
                    active_target, jpeg = await loop.run_in_executor(None, self._process_real_frame_sync, frame)
                    if jpeg is not None:
                        self._latest_jpeg = jpeg

                    perception_payload = {
                        "target_person": self.target_person or {
                            "x_center": 0.5,
                            "bbox_width": 0.0,
                            "confidence": 0.0,
                        },
                        "target_cat": self.target_cat,
                        "target_dog": self.target_dog,
                        "target_object": self.target_object,
                        "detected_objects": self.detected_objects,
                        "person_detected": self.person_detected,
                        "cat_detected": self.cat_detected,
                        "dog_detected": self.dog_detected,
                    }
                    if self.controller:
                        self.controller.set_perception_target(perception_payload)
                    self.frame_count += 1

                if self._frame_event is not None:
                    self._frame_event.set()
                    self._frame_event.clear()

                dt = time.monotonic() - self.last_frame_time if self.last_frame_time > 0 else 0.1
                self.last_frame_time = time.monotonic()
                if dt > 0:
                    inst_fps = 1.0 / dt
                    self.fps = 0.8 * self.fps + 0.2 * inst_fps if self.fps > 0 else inst_fps

                now_log = time.monotonic()
                if now_log - last_rate_log >= 1.0:
                    last_rate_log = now_log
                    conf_pct = round(self.last_raw_confidence * 100.0, 1)
                    person_str = "PERSON" if self.person_detected else "NO_PERSON"
                    cat_str = f", CAT {int(self.target_cat['confidence']*100)}%" if self.cat_detected and self.target_cat else ""
                    dog_str = f", DOG {int(self.target_dog['confidence']*100)}%" if self.dog_detected and self.target_dog else ""
                    msg = (
                        f"[VISION] Detection: {person_str} ({conf_pct:.1f}%){cat_str}{dog_str} "
                        f"(backend={self.detector_backend}, fps={self.fps:.1f}, objects={len(self.detected_objects)})"
                    )
                    print(msg, flush=True)
                    logger.info(msg)

                # Target ~15 FPS with minimal artificial sleep when processing is busy
                elapsed = time.monotonic() - t_start
                await asyncio.sleep(max(0.005, 0.065 - elapsed))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Vision loop error: {e}")
                self._consecutive_failures += 1
                await asyncio.sleep(0.2)
