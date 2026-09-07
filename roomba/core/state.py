"""
State models and drive command structures.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class SafetyState(str, Enum):
    DISARMED = "DISARMED"
    ARMED = "ARMED"
    ESTOP = "ESTOP"


@dataclass
class DriveCommand:
    """Independent left and right wheel velocities in mm/s (-500 to 500)."""
    left: int = 0
    right: int = 0

    def clamp(self) -> DriveCommand:
        return DriveCommand(
            left=max(-500, min(500, int(self.left))),
            right=max(-500, min(500, int(self.right))),
        )

    @property
    def is_zero(self) -> bool:
        return self.left == 0 and self.right == 0

    @classmethod
    def stop(cls) -> DriveCommand:
        return cls(0, 0)

    @classmethod
    def forward(cls, speed: int) -> DriveCommand:
        return cls(speed, speed)

    @classmethod
    def backward(cls, speed: int) -> DriveCommand:
        return cls(-speed, -speed)

    @classmethod
    def spin_left(cls, speed: int) -> DriveCommand:
        return cls(-speed, speed)

    @classmethod
    def spin_right(cls, speed: int) -> DriveCommand:
        return cls(speed, -speed)


@dataclass
class RobotState:
    connected: bool = False
    port: Optional[str] = None
    is_mock: bool = False
    armed: bool = False
    is_driving: bool = False
    mode: str = "Off"
    active_behavior: Optional[str] = None
