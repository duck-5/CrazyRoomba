"""
Camera and Image Acquisition Abstraction.
Supports USB webcams (V4L2 auto-discovery), Raspberry Pi 5 CSI cameras
(Picamera2 / rpicam-vid / libcamera-vid), and simulated frames.
"""

from __future__ import annotations

import asyncio
import glob
import logging
import os
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Any, List, Dict

logger = logging.getLogger("roomba.perception.camera")

# Kernel V4L2 nodes on Raspberry Pi 4/5 that are ISP/decoder/metadata nodes,
# NOT directly openable as standard USB UVC webcams via cv2.VideoCapture.
_PI_NON_CAMERA_PREFIXES = (
    "pispbe",
    "rp1-cfe",
    "rpi-hevc-dec",
    "bcm2835-codec",
    "bcm2835-isp",
    "vc4-",
    "vivid",
)


def discover_video_devices() -> List[Dict[str, Any]]:
    """
    Discover available /dev/video* devices on Linux with their sysfs names.
    Returns a sorted list of dicts: [{"index": int, "path": str, "name": str, "is_pi_internal": bool}, ...].
    """
    devices: List[Dict[str, Any]] = []
    if not sys.platform.startswith("linux"):
        return devices

    paths = sorted(
        glob.glob("/dev/video*"),
        key=lambda p: int(p.replace("/dev/video", "")) if p.replace("/dev/video", "").isdigit() else 9999,
    )
    for dev_path in paths:
        suffix = dev_path.replace("/dev/video", "")
        if not suffix.isdigit():
            continue
        idx = int(suffix)
        name_file = Path(f"/sys/class/video4linux/video{idx}/name")
        name = ""
        try:
            if name_file.exists():
                name = name_file.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            name = ""

        lower_name = name.lower()
        is_pi_internal = any(lower_name.startswith(prefix) for prefix in _PI_NON_CAMERA_PREFIXES)
        devices.append({
            "index": idx,
            "path": dev_path,
            "name": name or f"video{idx}",
            "is_pi_internal": is_pi_internal,
        })
    return devices


class BaseCameraSource(ABC):
    """Abstract interface for camera inputs."""

    def __init__(self, device_index: int = 0):
        self.device_index = device_index
        self.device_path: Optional[str] = None
        self.backend_name: str = "unknown"
        self.is_open = False

    @abstractmethod
    async def open(self) -> bool:
        """Initialize and open the camera device."""
        pass

    @abstractmethod
    async def read_frame(self) -> Optional[Any]:
        """Read the next video frame."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Release camera resources."""
        pass


class MockCameraSource(BaseCameraSource):
    """Simulation camera producing synthetic test patterns."""

    def __init__(self, device_index: int = 0):
        super().__init__(device_index)
        self.backend_name = "mock"
        self._frame_count = 0

    async def open(self) -> bool:
        self.is_open = True
        logger.info("MockCameraSource opened.")
        return True

    async def read_frame(self) -> Optional[bytes]:
        if not self.is_open:
            return None
        self._frame_count += 1
        # Placeholder 1x1 GIF / mock byte string
        return b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x01D\x00;"

    async def close(self) -> None:
        self.is_open = False
        logger.info("MockCameraSource closed.")


class OpenCVCameraSource(BaseCameraSource):
    """
    Camera source using OpenCV to capture from USB or V4L2 cameras.
    Supports explicit index/path or automatic scanning across /dev/video* on Linux/Pi 5.
    """

    def __init__(
        self,
        device_index: int = 0,
        width: int = 640,
        height: int = 480,
        device_path: Optional[str] = None,
        auto_scan: bool = True,
    ):
        super().__init__(device_index)
        self.width = width
        self.height = height
        self.device_path = device_path
        self.auto_scan = auto_scan
        self.backend_name = "opencv"
        self.cap = None
        self._cv2 = None

    def _try_open_candidate_sync(self, cv2: Any, target: int | str) -> Any:
        """
        Try opening a specific OpenCV VideoCapture target (index or /dev/videoN)
        and verify that at least one real frame can be grabbed.
        """
        backends = [cv2.CAP_V4L2, cv2.CAP_ANY] if sys.platform.startswith("linux") else [cv2.CAP_ANY]
        for backend in backends:
            cap = None
            try:
                cap = cv2.VideoCapture(target, backend) if backend != cv2.CAP_ANY else cv2.VideoCapture(target)
                if not cap.isOpened():
                    cap.release()
                    continue

                if sys.platform.startswith("linux"):
                    # Request MJPG when possible for reliable USB bandwidth on Raspberry Pi
                    try:
                        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                    except Exception:
                        pass
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)

                # Verify that the node actually delivers frames (filters out V4L2 metadata nodes)
                got_frame = False
                for _ in range(3):
                    ret, frame = cap.read()
                    if ret and frame is not None and getattr(frame, "size", 0) > 0:
                        got_frame = True
                        break
                if got_frame:
                    return cap

                cap.release()
            except Exception:
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass
        return None

    def _open_sync(self) -> bool:
        import cv2
        self._cv2 = cv2

        candidates: List[int | str] = []
        if self.device_path:
            candidates.append(self.device_path)
        else:
            candidates.append(self.device_index)

        if self.auto_scan:
            if sys.platform.startswith("linux"):
                discovered = discover_video_devices()
                # Prioritize non-Pi-internal V4L2 nodes (USB webcams), then others
                for dev in discovered:
                    if not dev["is_pi_internal"] and dev["path"] not in candidates and dev["index"] not in candidates:
                        candidates.append(dev["path"])
                for idx in range(0, 4):
                    if idx not in candidates and f"/dev/video{idx}" not in candidates:
                        # Skip if explicitly known to be a Pi internal ISP/codec node
                        matching = [d for d in discovered if d["index"] == idx]
                        if matching and matching[0]["is_pi_internal"]:
                            continue
                        candidates.append(idx)
            else:
                for idx in range(0, 3):
                    if idx not in candidates:
                        candidates.append(idx)

        for target in candidates:
            cap = self._try_open_candidate_sync(cv2, target)
            if cap is not None:
                self.cap = cap
                if isinstance(target, str):
                    self.device_path = target
                    suffix = target.replace("/dev/video", "")
                    if suffix.isdigit():
                        self.device_index = int(suffix)
                else:
                    self.device_index = target
                    if sys.platform.startswith("linux"):
                        self.device_path = f"/dev/video{target}"
                self.backend_name = "opencv-v4l2" if sys.platform.startswith("linux") else "opencv"
                return True

        return False

    async def open(self) -> bool:
        if self.is_open:
            return True
        try:
            loop = asyncio.get_running_loop()
            opened = await loop.run_in_executor(None, self._open_sync)
            if not opened:
                logger.warning(f"Failed to open OpenCV camera (initial index={self.device_index})")
                return False
            self.is_open = True
            logger.info(f"OpenCVCameraSource opened (index={self.device_index}, path={self.device_path})")
            return True
        except Exception as e:
            logger.error(f"cv2 failed to load or open camera: {e}")
            return False

    async def read_frame(self) -> Optional[Any]:
        if not self.is_open or self.cap is None or self._cv2 is None:
            return None

        loop = asyncio.get_running_loop()
        ret, frame = await loop.run_in_executor(None, self.cap.read)
        if not ret:
            logger.warning("Failed to grab frame from OpenCV camera.")
            return None
        return frame

    async def close(self) -> None:
        self.is_open = False
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        logger.info("OpenCVCameraSource closed.")


class Picamera2CameraSource(BaseCameraSource):
    """Camera source using Raspberry Pi `picamera2` (libcamera) for Pi 5 CSI cameras."""

    def __init__(self, device_index: int = 0, width: int = 640, height: int = 480):
        super().__init__(device_index)
        self.width = width
        self.height = height
        self.backend_name = "picamera2"
        self._picam2: Any = None
        self._cv2: Any = None

    def _open_sync(self) -> bool:
        from picamera2 import Picamera2  # type: ignore
        import cv2
        self._cv2 = cv2

        picam2 = Picamera2(camera_num=self.device_index)
        cfg = picam2.create_video_configuration(
            main={"size": (self.width, self.height), "format": "RGB888"}
        )
        picam2.configure(cfg)
        picam2.start()
        frame = picam2.capture_array()
        if frame is None or getattr(frame, "size", 0) == 0:
            picam2.stop()
            picam2.close()
            return False
        self._picam2 = picam2
        return True

    async def open(self) -> bool:
        if self.is_open:
            return True
        try:
            loop = asyncio.get_running_loop()
            opened = await loop.run_in_executor(None, self._open_sync)
            if not opened:
                return False
            self.is_open = True
            self.device_path = f"picamera2:{self.device_index}"
            logger.info(f"Picamera2CameraSource opened (camera_num={self.device_index})")
            return True
        except ImportError:
            return False
        except Exception as e:
            logger.debug(f"Picamera2 unavailable or failed to open: {e}")
            return False

    async def read_frame(self) -> Optional[Any]:
        if not self.is_open or self._picam2 is None or self._cv2 is None:
            return None
        loop = asyncio.get_running_loop()

        def _grab():
            rgb = self._picam2.capture_array()
            if rgb is None:
                return None
            return self._cv2.cvtColor(rgb, self._cv2.COLOR_RGB2BGR)

        return await loop.run_in_executor(None, _grab)

    async def close(self) -> None:
        self.is_open = False
        if self._picam2 is not None:
            try:
                self._picam2.stop()
                self._picam2.close()
            except Exception:
                pass
            self._picam2 = None
        logger.info("Picamera2CameraSource closed.")


class LibcameraCLISource(BaseCameraSource):
    """
    Camera source using `rpicam-vid` or `libcamera-vid` MJPEG stdout stream.
    Works on Raspberry Pi 5 Bookworm CSI cameras without needing picamera2 Python bindings.
    """

    def __init__(self, device_index: int = 0, width: int = 640, height: int = 480, fps: int = 15):
        super().__init__(device_index)
        self.width = width
        self.height = height
        self.fps = fps
        self.backend_name = "libcamera-cli"
        self._proc: Optional[subprocess.Popen] = None
        self._buffer = bytearray()
        self._cv2: Any = None
        self._np: Any = None

    @staticmethod
    def find_cli() -> Optional[str]:
        for cmd in ("rpicam-vid", "libcamera-vid"):
            path = shutil.which(cmd)
            if path:
                return path
        return None

    async def open(self) -> bool:
        if self.is_open:
            return True
        cli = self.find_cli()
        if not cli:
            return False

        try:
            import cv2
            import numpy as np
            self._cv2 = cv2
            self._np = np
        except ImportError:
            return False

        cmd = [
            cli,
            "--camera", str(self.device_index),
            "--codec", "mjpeg",
            "--inline",
            "-t", "0",
            "--width", str(self.width),
            "--height", str(self.height),
            "--framerate", str(self.fps),
            "--nopreview",
            "-o", "-",
        ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
            # Verify first JPEG frame arrives within ~3s
            loop = asyncio.get_running_loop()
            frame = await asyncio.wait_for(
                loop.run_in_executor(None, self._read_frame_sync),
                timeout=3.0,
            )
            if frame is None:
                await self.close()
                return False
            self.is_open = True
            self.device_path = f"{os.path.basename(cli)}:{self.device_index}"
            logger.info(f"LibcameraCLISource opened via {cli}")
            return True
        except Exception as e:
            logger.debug(f"LibcameraCLISource failed: {e}")
            await self.close()
            return False

    def _read_frame_sync(self) -> Optional[Any]:
        if self._proc is None or self._proc.stdout is None:
            return None

        while True:
            if self._proc.poll() is not None:
                return None
            chunk = self._proc.stdout.read(4096)
            if not chunk:
                return None
            self._buffer.extend(chunk)

            soi = self._buffer.find(b"\xff\xd8")
            if soi == -1:
                if len(self._buffer) > 65536:
                    self._buffer.clear()
                continue
            if soi > 0:
                del self._buffer[:soi]

            eoi = self._buffer.find(b"\xff\xd9", 2)
            if eoi != -1:
                jpg = bytes(self._buffer[: eoi + 2])
                del self._buffer[: eoi + 2]
                arr = self._np.frombuffer(jpg, dtype=self._np.uint8)
                frame = self._cv2.imdecode(arr, self._cv2.IMREAD_COLOR)
                if frame is not None:
                    return frame

    async def read_frame(self) -> Optional[Any]:
        if not self.is_open or self._proc is None:
            return None
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._read_frame_sync)

    async def close(self) -> None:
        self.is_open = False
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        self._buffer.clear()
        logger.info("LibcameraCLISource closed.")
