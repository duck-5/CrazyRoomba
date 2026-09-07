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
