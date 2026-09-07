"""
Base mode abstractions and runtime robot context.
Defines the interface for autonomous Roomba operating modes and scripts.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, TYPE_CHECKING
from roomba.core.state import DriveCommand

if TYPE_CHECKING:
    from roomba.core.controller import RobotController


class RobotContext:
    """Read-only context passed to operating modes on every control tick."""

    def __init__(
        self,
        controller: "RobotController",
        telemetry: Dict[str, Any],
        perception: Optional[Dict[str, Any]] = None,
    ):
        self.controller = controller
        self.telemetry = telemetry
        self.perception = perception or {}
        self.timestamp = time.monotonic()

    @property
    def is_armed(self) -> bool:
        return self.controller.armed

    @property
    def is_connected(self) -> bool:
        return self.controller.is_connected

    @property
    def bumps_and_drops(self) -> Dict[str, bool]:
        return self.telemetry.get("bumps_and_drops", {})

    @property
    def is_bumped(self) -> bool:
        b = self.bumps_and_drops
        return bool(b.get("bump_left") or b.get("bump_right"))

    @property
    def is_wheel_dropped(self) -> bool:
        b = self.bumps_and_drops
        return bool(b.get("wheel_drop_left") or b.get("wheel_drop_right"))

    @property
    def cliffs(self) -> Dict[str, bool]:
        return self.telemetry.get("cliffs", {})

    @property
    def is_cliff_detected(self) -> bool:
        c = self.cliffs
        return bool(
            c.get("cliff_left")
            or c.get("cliff_front_left")
            or c.get("cliff_front_right")
            or c.get("cliff_right")
        )

    @property
    def battery_percent(self) -> float:
        return float(self.telemetry.get("battery_percent", 0.0))


class BaseMode(ABC):
    """
    Abstract base class for all autonomous modes, scripts, and controllers.
    Subclasses define autonomous routines such as person-following, wandering, or line-following.
    """

    name: str = "base_mode"
    description: str = "Base mode"

    def __init__(self):
        self.is_active = False

    async def on_start(self, context: RobotContext) -> None:
        """Called once when the mode is activated."""
        self.is_active = True

    @abstractmethod
    async def update(self, context: RobotContext) -> Optional[DriveCommand]:
        """
        Called periodically (default: 10 Hz) while active.
        Returns a DriveCommand to control the motors, or None to keep current motion.
        """
        pass

    async def on_stop(self, context: RobotContext) -> None:
        """Called when the mode is deactivated or overridden."""
        self.is_active = False


# Backward-compatible alias
BaseBehavior = BaseMode
