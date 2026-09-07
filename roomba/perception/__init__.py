"""
Perception and Camera Pipeline Interfaces.
Provides camera frame acquisition and detection abstractions for vision tasks.
"""

from .camera import BaseCameraSource, MockCameraSource

__all__ = [
    "BaseCameraSource",
    "MockCameraSource",
]
