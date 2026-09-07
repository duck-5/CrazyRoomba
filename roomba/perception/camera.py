"""
Camera and Image Acquisition Abstraction.
Supports USB webcams, Raspberry Pi Camera Module, and simulated frames.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional, Any

logger = logging.getLogger("roomba.perception.camera")


class BaseCameraSource(ABC):
    """Abstract interface for camera inputs."""

    def __init__(self, device_index: int = 0):
        self.device_index = device_index
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
    """Camera source using OpenCV to capture from USB or Pi camera."""

    def __init__(self, device_index: int = 0, width: int = 640, height: int = 480):
        super().__init__(device_index)
        self.width = width
        self.height = height
        self.cap = None
        self._cv2 = None

    async def open(self) -> bool:
        if self.is_open:
            return True
        try:
            import cv2
            self._cv2 = cv2
            # Use V4L2 backend on Linux, DirectShow on Windows, default elsewhere
            self.cap = cv2.VideoCapture(self.device_index)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            if not self.cap.isOpened():
                logger.error(f"Failed to open OpenCV camera at index {self.device_index}")
                return False
            self.is_open = True
            logger.info(f"OpenCVCameraSource opened (index={self.device_index})")
            return True
        except ImportError:
            logger.error("cv2 module not found. Please install opencv-python.")
            return False

    async def read_frame(self) -> Optional[Any]:
        if not self.is_open or self.cap is None or self._cv2 is None:
            return None
        
        # Run synchronous cv2 read in a thread pool to avoid blocking the asyncio event loop
        loop = asyncio.get_running_loop()
        ret, frame = await loop.run_in_executor(None, self.cap.read)
        if not ret:
            logger.warning("Failed to grab frame from OpenCV camera.")
            return None
        return frame

    async def close(self) -> None:
        self.is_open = False
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        logger.info("OpenCVCameraSource closed.")
