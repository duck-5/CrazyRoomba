"""
Manual teleoperation mode.
Default mode where motor commands are directed by human input (web UI, keyboard, D-pad).
"""

from __future__ import annotations

from typing import Optional
from roomba.modes.base import BaseMode, RobotContext
from roomba.core.state import DriveCommand


class ManualMode(BaseMode):
    name: str = "manual"
    description: str = "Manual teleoperation via Web cockpit, keyboard WASD, and D-Pad"

    async def update(self, context: RobotContext) -> Optional[DriveCommand]:
        # Manual mode does not issue autonomous drive commands;
        # motor commands come directly via drive API/WebSocket.
        return None


# Backward-compatible alias
ManualTeleopBehavior = ManualMode
