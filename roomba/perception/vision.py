"""
Integrated Camera & Person Vision Service for Roomba 960 (Raspberry Pi 5).
Provides:
- Resilient camera initialization (never crashes if camera or OpenCV is missing)
- Built-in offline person detection using OpenCV HOGDescriptor (no external weights needed)
- Live annotated MJPEG frame generation for the Web Cockpit
- Automatic perception injection into RobotController for FollowPersonMode
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
import urllib.request
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

from roomba.perception.camera import (
    BaseCameraSource,
    OpenCVCameraSource,
    MockCameraSource,
    Picamera2CameraSource,
    LibcameraCLISource,
    discover_video_devices,
)
from roomba.config import config, BASE_DIR

_MOBILENET_PROTOTXT_URL = "https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/voc/MobileNetSSD_deploy.prototxt"
_MOBILENET_MODEL_URL = "https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/mobilenet_iter_73000.caffemodel"
_MOBILENET_PERSON_CLASS_ID = 15

logger = logging.getLogger("roomba.perception.vision")


class VisionService:
    """Manages camera capture, person detection, and MJPEG preview frames."""

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
        self.detector_backend: str = "none"  # "hog" | "mock" | "none"

        self.person_detected: bool = False
        self.target_person: Optional[Dict[str, Any]] = None
        self.fps: float = 0.0
        self.frame_count: int = 0
        self.last_frame_time: float = 0.0

        self._latest_jpeg: Optional[bytes] = None
        self._frame_event: Optional[asyncio.Event] = None
        self._loop_task: Optional[asyncio.Task] = None
        self._ssd_net: Any = None
        self._hog: Any = None
        self._cv2: Any = None
        self._consecutive_failures: int = 0

    def get_status(self) -> Dict[str, Any]:
        """Return current camera & vision status dictionary."""
        return {
            "available": self.available,
            "status": self.status,
            "is_mock": self.is_mock,
            "device_index": self.device_index,
            "device_path": self.device_path,
            "camera_backend": self.camera_backend,
            "rotation": self.rotation,
            "detector_backend": self.detector_backend,
            "error": self.error,
            "person_detected": self.person_detected,
            "target_person": self.target_person,
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
        Safely initialize camera and person detector.
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

        # Initialize person detector (MobileNet-SSD primary, HOG fallback)
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

        # Auto-download to cache if missing
        cache_dir = Path.home() / ".cache" / "roomba" / "models"
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            proto = cache_dir / "MobileNetSSD_deploy.prototxt"
            model = cache_dir / "mobilenet_iter_73000.caffemodel"
            if not proto.exists():
                logger.info("Downloading MobileNetSSD_deploy.prototxt...")
                urllib.request.urlretrieve(_MOBILENET_PROTOTXT_URL, str(proto))
            if not model.exists() or model.stat().st_size < 1_000_000:
                logger.info("Downloading mobilenet_iter_73000.caffemodel (~23MB)...")
                urllib.request.urlretrieve(_MOBILENET_MODEL_URL, str(model))
            return proto, model
        except Exception as e:
            logger.warning(f"Could not download MobileNet-SSD model: {e}")
            return None

    def _init_detector_sync(self, cv2: Any) -> None:
        """Initialize MobileNet-SSD DNN person detector, falling back to HOG."""
        self._ssd_net = None
        self._hog = None
        self.detector_backend = "none"

        paths = self._resolve_mobilenet_paths()
        if paths is not None:
            proto, model = paths
            try:
                net = cv2.dnn.readNetFromCaffe(str(proto), str(model))
                self._ssd_net = net
                self.detector_backend = "mobilenet-ssd"
                logger.info(f"Person detector initialized: MobileNet-SSD ({model})")
                return
            except Exception as e:
                logger.warning(f"MobileNet-SSD load failed, falling back to HOG: {e}")

        try:
            hog = cv2.HOGDescriptor()
            hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
            self._hog = hog
            self.detector_backend = "hog"
            logger.info("Person detector initialized: OpenCV HOG")
        except Exception as e:
            logger.warning(f"HOG detector init failed: {e}")
            self._hog = None
            self.detector_backend = "none"

    def _process_real_frame_sync(self, frame: Any) -> Tuple[Optional[Dict[str, Any]], Optional[bytes]]:
        """Run optional rotation, person detection (MobileNet-SSD / HOG), and draw overlay on frame."""
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
        target = None
        best_conf = 0.0
        best_box: Optional[Tuple[int, int, int, int]] = None

        if self._ssd_net is not None:
            resized = cv2.resize(frame, (300, 300))
            blob = cv2.dnn.blobFromImage(resized, 0.007843, (300, 300), 127.5)
            self._ssd_net.setInput(blob)
            detections = self._ssd_net.forward()
            num_det = detections.shape[2] if len(detections.shape) >= 3 else 0
            for i in range(num_det):
                conf = float(detections[0, 0, i, 2])
                class_id = int(detections[0, 0, i, 1])
                if class_id == _MOBILENET_PERSON_CLASS_ID and conf > 0.35 and conf > best_conf:
                    x1 = max(0, int(detections[0, 0, i, 3] * w))
                    y1 = max(0, int(detections[0, 0, i, 4] * h))
                    x2 = min(w, int(detections[0, 0, i, 5] * w))
                    y2 = min(h, int(detections[0, 0, i, 6] * h))
                    if x2 > x1 and y2 > y1:
                        best_conf = conf
                        best_box = (x1, y1, x2 - x1, y2 - y1)

        elif self._hog is not None:
            # Resize for fast CPU inference on Raspberry Pi 5
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

            for idx, (rx, ry, rw, rh) in enumerate(rects):
                if idx < len(weights):
                    raw_w = weights[idx]
                    weight = float(raw_w.item()) if hasattr(raw_w, "item") else float(raw_w)
                else:
                    weight = 0.5
                # Map HOG SVM score to ~0..1 confidence
                conf = min(1.0, max(0.0, weight / 1.5))
                if conf > 0.35 and conf > best_conf:
                    best_conf = conf
                    best_box = (
                        int(rx / scale),
                        int(ry / scale),
                        int(rw / scale),
                        int(rh / scale),
                    )

        if best_box is not None:
            bx, by, bw, bh = best_box
            x_center = (bx + bw / 2.0) / float(w)
            bbox_width = bw / float(w)
            target = {
                "x_center": round(x_center, 4),
                "bbox_width": round(bbox_width, 4),
                "confidence": round(best_conf, 3),
                "bbox": [bx, by, bw, bh],
            }
            cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (0, 230, 118), 2)
            label = f"PERSON {int(best_conf * 100)}%"
            cv2.putText(
                frame,
                label,
                (bx, max(20, by - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 230, 118),
                2,
            )

        # Overlay HUD status
        mode_text = "FOLLOW ACTIVE" if (
            self.controller and getattr(self.controller.mode_manager, "active_name", "") == "follow_person"
        ) else "VISION READY"
        cv2.putText(
            frame,
            f"{mode_text} | {self.fps:.1f} FPS",
            (10, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            1,
        )

        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
        jpeg = buf.tobytes() if ok else None
        return target, jpeg

    def _generate_mock_frame_sync(self, t: float) -> Tuple[Dict[str, Any], Optional[bytes]]:
        """Generate a synthetic camera frame with a moving simulated person."""
        # Sinusoidal horizontal movement across frame
        x_center = 0.5 + 0.25 * math.sin(t * 0.8)
        bbox_width = 0.30 + 0.05 * math.cos(t * 0.5)
        target = {
            "x_center": round(x_center, 4),
            "bbox_width": round(bbox_width, 4),
            "confidence": 0.92,
        }

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

            bw = int(bbox_width * w)
            bh = int(bw * 1.8)
            cx = int(x_center * w)
            cy = h // 2
            bx = max(0, cx - bw // 2)
            by = max(10, cy - bh // 2)

            cv2.rectangle(frame, (bx, by), (min(w - 1, bx + bw), min(h - 1, by + bh)), (0, 230, 118), 2)
            cv2.circle(frame, (cx, by + 20), 14, (0, 230, 118), 2)
            cv2.putText(frame, "MOCK PERSON 92%", (bx, max(18, by - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 230, 118), 1)
            cv2.putText(frame, "MOCK CAMERA SIM", (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 200, 220), 1)

            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
            if ok:
                jpeg = buf.tobytes()

        return target, jpeg

    async def _vision_loop(self) -> None:
        """Background loop reading frames, detecting persons, and updating controller perception."""
        loop = asyncio.get_running_loop()
        while self.available and self.camera is not None:
            t_start = time.monotonic()
            try:
                if self.is_mock:
                    target, jpeg = await loop.run_in_executor(None, self._generate_mock_frame_sync, t_start)
                    self.person_detected = True
                    self.target_person = target
                    if jpeg is not None:
                        self._latest_jpeg = jpeg
                    if self.controller:
                        self.controller.set_perception_target({"target_person": target})
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
                    target, jpeg = await loop.run_in_executor(None, self._process_real_frame_sync, frame)
                    if jpeg is not None:
                        self._latest_jpeg = jpeg

                    if target is not None:
                        self.person_detected = True
                        self.target_person = target
                        if self.controller:
                            self.controller.set_perception_target({"target_person": target})
                    else:
                        self.person_detected = False
                        self.target_person = None
                        if self.controller:
                            self.controller.set_perception_target({
                                "target_person": {
                                    "x_center": 0.5,
                                    "bbox_width": 0.0,
                                    "confidence": 0.0,
                                }
                            })
                    self.frame_count += 1

                if self._frame_event is not None:
                    self._frame_event.set()
                    self._frame_event.clear()

                dt = time.monotonic() - self.last_frame_time if self.last_frame_time > 0 else 0.1
                self.last_frame_time = time.monotonic()
                if dt > 0:
                    inst_fps = 1.0 / dt
                    self.fps = 0.8 * self.fps + 0.2 * inst_fps if self.fps > 0 else inst_fps

                # Target ~15 FPS with minimal artificial sleep when processing is busy
                elapsed = time.monotonic() - t_start
                await asyncio.sleep(max(0.005, 0.065 - elapsed))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Vision loop error: {e}")
                self._consecutive_failures += 1
                await asyncio.sleep(0.2)
