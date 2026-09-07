"""
Autonomous Wander & Obstacle Avoidance Mode.
Demonstrates autonomous decision-making using live bumper and cliff sensors.
"""

from __future__ import annotations

import asyncio
import time
import random
from typing import Optional
from roomba.modes.base import BaseMode, RobotContext
from roomba.core.state import DriveCommand


class WanderMode(BaseMode):
    name: str = "wander"
    description: str = "Autonomous wandering with bumper & cliff obstacle avoidance"

    def __init__(self, cruise_speed: int = 150):
        super().__init__()
        self.cruise_speed = cruise_speed
        self._state = "FORWARD"
        self._state_timer = 0.0
        self._turn_direction = 1  # 1 for right, -1 for left

    async def on_start(self, context: RobotContext) -> None:
        await super().on_start(context)
        self._state = "FORWARD"
        self._state_timer = time.monotonic()
        context.controller.log_event("info", "WanderMode: Started autonomous exploration")

    async def update(self, context: RobotContext) -> Optional[DriveCommand]:
        now = time.monotonic()

        # Check safety: bumps or cliffs
        if self._state == "FORWARD":
            if context.is_bumped or context.is_cliff_detected:
                self._state = "BACKUP"
                self._state_timer = now + 0.8
                # Choose turn direction based on which bumper hit
                bump_l = context.bumps_and_drops.get("bump_left", False)
                bump_r = context.bumps_and_drops.get("bump_right", False)
                if bump_l and not bump_r:
                    self._turn_direction = 1  # turn right
                elif bump_r and not bump_l:
                    self._turn_direction = -1  # turn left
                else:
                    self._turn_direction = random.choice([-1, 1])

                context.controller.log_event("warn", "WanderMode: Obstacle hit, backing up")
                return DriveCommand.backward(self.cruise_speed)
            return DriveCommand.forward(self.cruise_speed)

        elif self._state == "BACKUP":
            if now >= self._state_timer:
                self._state = "TURN"
                self._state_timer = now + random.uniform(0.6, 1.2)
                context.controller.log_event("info", "WanderMode: Turning away from obstacle")
                return DriveCommand(
                    left=self.cruise_speed * self._turn_direction,
                    right=-self.cruise_speed * self._turn_direction,
                )
            return DriveCommand.backward(self.cruise_speed)

        elif self._state == "TURN":
            if now >= self._state_timer:
                self._state = "FORWARD"
                context.controller.log_event("info", "WanderMode: Resuming forward drive")
                return DriveCommand.forward(self.cruise_speed)
            return DriveCommand(
                left=self.cruise_speed * self._turn_direction,
                right=-self.cruise_speed * self._turn_direction,
            )

        return DriveCommand.stop()

    async def on_stop(self, context: RobotContext) -> None:
        await super().on_stop(context)
        context.controller.log_event("info", "WanderMode: Stopped")


# Backward-compatible alias
WanderBehavior = WanderMode
