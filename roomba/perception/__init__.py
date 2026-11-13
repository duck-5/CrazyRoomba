"""
Perception and Camera Pipeline Interfaces.
Provides camera frame acquisition and detection abstractions for vision tasks.
"""

from .camera import BaseCameraSource, MockCameraSource, OpenCVCameraSource
from .vision import VisionService

__all__ = [
    "BaseCameraSource",
    "MockCameraSource",
    "OpenCVCameraSource",
    "VisionService",
]
