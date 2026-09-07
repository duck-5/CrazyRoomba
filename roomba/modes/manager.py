"""
Mode Manager and Arbitrator.
Registers autonomous modes, coordinates mode transitions, and executes the active mode control loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional, Any, TYPE_CHECKING
from roomba.modes.base import BaseMode, RobotContext
from roomba.modes.manual import ManualMode
from roomba.core.state import DriveCommand

if TYPE_CHECKING:
    from roomba.core.controller import RobotController

logger = logging.getLogger("roomba.modes.manager")


class ModeManager:
    """Coordinates and executes autonomous operating mode scripts."""

    def __init__(self, controller: "RobotController"):
        self.controller = controller
        self._modes: Dict[str, BaseMode] = {}
        self._active_mode: BaseMode = ManualMode()
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

        # Register default manual mode
        self.register(self._active_mode)

    @property
    def active_name(self) -> str:
        return self._active_mode.name

    @property
    def active_mode(self) -> BaseMode:
        return self._active_mode

    # Alias for behavior compatibility
    @property
    def active_behavior(self) -> BaseMode:
        return self._active_mode

    def register(self, mode: BaseMode) -> None:
        """Register a new mode in the catalog."""
        self._modes[mode.name] = mode
        logger.info(f"Registered mode: {mode.name} - {mode.description}")

    def list_modes(self) -> List[Dict[str, Any]]:
        """Return list of all registered modes and their active status."""
        return [
            {
                "name": m.name,
                "description": m.description,
                "active": (m.name == self.active_name),
            }
            for m in self._modes.values()
        ]

    # Alias for behavior compatibility
    def list_behaviors(self) -> List[Dict[str, Any]]:
        return self.list_modes()

    async def set_active(self, name: str) -> None:
        """Switch the active operating mode."""
        async with self._lock:
            if name not in self._modes:
                raise KeyError(f"Mode '{name}' is not registered. Available: {list(self._modes.keys())}")

            if name == self.active_name:
                return

            context = self._build_context()
            await self._active_mode.on_stop(context)

            self._active_mode = self._modes[name]
            await self._active_mode.on_start(context)
            self.controller.log_event("info", f"Operating mode switched to: {name}")

    async def stop_active(self) -> None:
        """Revert to default manual teleoperation."""
        await self.set_active("manual")

    def start_loop(self, rate_hz: float = 10.0) -> None:
        """Start the background mode evaluation loop."""
        self.stop_loop()
        self._task = asyncio.create_task(self._run_loop(rate_hz))

    def stop_loop(self) -> None:
        """Stop the background mode loop."""
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    def _build_context(self) -> RobotContext:
        telemetry = self.controller.latest_telemetry
        perception = getattr(self.controller, "latest_perception", {})
        return RobotContext(
            controller=self.controller,
            telemetry=telemetry,
            perception=perception,
        )

    async def _run_loop(self, rate_hz: float) -> None:
        interval = 1.0 / max(1.0, rate_hz)
        logger.info(f"Mode loop started at {rate_hz} Hz")

        while True:
            try:
                # If robot is not connected or disarmed, halt autonomous drive
                if self.controller.is_connected and self.controller.armed:
                    if self.active_name != "manual":
                        context = self._build_context()
                        cmd = await self._active_mode.update(context)
                        if cmd is not None:
                            await self.controller.drive(cmd.left, cmd.right)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Error in mode '{self.active_name}' update: {e}")

            await asyncio.sleep(interval)


# Backward-compatible alias
BehaviorManager = ModeManager
