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
from typing import Optional, Dict, Any, Tuple

from roomba.perception.camera import BaseCameraSource, OpenCVCameraSource, MockCameraSource
from roomba.config import config

logger = logging.getLogger("roomba.perception.vision")


class VisionService:
    """Manages camera capture, person detection, and MJPEG preview frames."""

    def __init__(self, controller: Any = None, device_index: Optional[int] = None):
        self.controller = controller
        self.device_index: int = config.camera_device_index if device_index is None else device_index

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
            "detector_backend": self.detector_backend,
            "error": self.error,
            "person_detected": self.person_detected,
            "target_person": self.target_person,
            "fps": round(self.fps, 1),
            "frame_count": self.frame_count,
        }

    async def initialize(self, mock: bool = False, device_index: Optional[int] = None) -> Dict[str, Any]:
        """
        Safely initialize camera and person detector.
        Never raises on missing hardware or missing OpenCV; records error state instead.
        """
        await self.stop()

        if device_index is not None:
            self.device_index = device_index

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

        cam = OpenCVCameraSource(device_index=self.device_index, width=640, height=480)
        opened = False
        try:
            opened = await cam.open()
        except Exception as e:
            logger.warning(f"Camera open exception: {e}")
            opened = False

        if not opened:
            self.camera = None
            self.available = False
            self.status = "error"
            self.detector_backend = "none"
            self.error = f"No camera detected at index {self.device_index}. Connect USB/Pi camera and click Try Again."
            logger.warning(self.error)
            if self.controller:
                self.controller.log_event("warn", self.error)
            return self.get_status()

        # Initialize built-in OpenCV HOG person detector (works offline, zero extra weights)
        try:
            hog = cv2.HOGDescriptor()
            hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
            self._hog = hog
            self.detector_backend = "hog"
        except Exception as e:
            logger.warning(f"HOG detector init failed: {e}")
            self._hog = None
            self.detector_backend = "none"

        self.camera = cam
        self.available = True
        self.status = "connected"
        self.error = None
        self._start_loop()
        if self.controller:
            self.controller.log_event("success", f"Camera connected (index={self.device_index}, detector={self.detector_backend})")
        return self.get_status()

    async def retry(self, mock: bool = False, device_index: Optional[int] = None) -> Dict[str, Any]:
        """Re-probe and attempt to initialize the camera."""
        return await self.initialize(mock=mock, device_index=device_index)

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

    def _process_real_frame_sync(self, frame: Any) -> Tuple[Optional[Dict[str, Any]], Optional[bytes]]:
        """Run HOG person detection and draw overlay on frame (called in thread executor)."""
        cv2 = self._cv2
        if cv2 is None or frame is None:
            return None, None

        h, w = frame.shape[:2]
        target = None

        if self._hog is not None:
            # Resize for fast CPU inference on Raspberry Pi 5
            target_w = 320
            scale = target_w / float(w)
            target_h = max(1, int(h * scale))
            small = cv2.resize(frame, (target_w, target_h))

            rects, weights = self._hog.detectMultiScale(
                small,
                winStride=(8, 8),
                padding=(4, 4),
                scale=1.05,
            )

            best_conf = 0.0
            best_box = None
            for idx, (rx, ry, rw, rh) in enumerate(rects):
                weight = float(weights[idx]) if idx < len(weights) else 0.5
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

                # Cap at ~12 FPS to keep Pi 5 CPU cool
                elapsed = time.monotonic() - t_start
                await asyncio.sleep(max(0.03, 0.085 - elapsed))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Vision loop error: {e}")
                self._consecutive_failures += 1
                await asyncio.sleep(0.2)
