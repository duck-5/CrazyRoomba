"""
Autonomous Wander & Obstacle Avoidance Mode for Roomba 960.
Features multi-layered obstacle avoidance:
1. Physical bumpers & cliff sensors (emergency reverse)
2. Non-contact infrared light bumpers (proactive smooth avoidance before collision)
3. Camera vision obstacle detection (furniture, walls, and obstructions)
"""

from __future__ import annotations

import time
import random
from typing import Optional, Dict, Any, List
from roomba.modes.base import BaseMode, RobotContext
from roomba.core.state import DriveCommand
from roomba.perception.classes import OBSTACLE_LABELS


class WanderMode(BaseMode):
    name: str = "wander"
    description: str = "Autonomous wandering with multi-sensor & vision obstacle avoidance"

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

        # 1. Critical safety override: Cliff or wheel drop detection in ANY state
        if context.is_cliff_detected or context.is_wheel_dropped:
            self._state = "BACKUP"
            self._state_timer = now + 1.0
            self._turn_direction = random.choice([-1, 1])
            context.controller.log_event("warn", "WanderMode: Cliff or drop detected, backing away immediately")
            return DriveCommand.backward(self.cruise_speed)

        # 2. Emergency bumper collision: transition to BACKUP if not already backing up
        if context.is_bumped and self._state != "BACKUP":
            self._state = "BACKUP"
            self._state_timer = now + 0.8
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

        # State-driven autonomous navigation
        if self._state == "FORWARD":
            # Proactive non-contact obstacle avoidance: IR Light Bumpers
            lb: Dict[str, Any] = context.telemetry.get("light_bumpers", {})
            center_blocked = lb.get("center_left") or lb.get("center_right")
            left_blocked = lb.get("front_left") or lb.get("left")
            right_blocked = lb.get("front_right") or lb.get("right")

            if center_blocked:
                # Proactive turn before physical impact
                self._state = "TURN"
                self._state_timer = now + random.uniform(0.6, 1.1)
                self._turn_direction = 1 if left_blocked else (-1 if right_blocked else random.choice([-1, 1]))
                context.controller.log_event("info", "WanderMode: Non-contact proximity ahead, turning")
                return DriveCommand(
                    left=self.cruise_speed * self._turn_direction,
                    right=-self.cruise_speed * self._turn_direction,
                )
            elif left_blocked:
                # Soft curve away from left wall/obstacle
                return DriveCommand(left=self.cruise_speed, right=max(40, self.cruise_speed // 2))
            elif right_blocked:
                # Soft curve away from right wall/obstacle
                return DriveCommand(left=max(40, self.cruise_speed // 2), right=self.cruise_speed)

            # Vision-based obstacle avoidance
            perception: Dict[str, Any] = context.perception or {}
            detected: List[Dict[str, Any]] = perception.get("detected_objects", [])
            for obj in detected:
                label = obj.get("label", "").lower()
                bbox_w = float(obj.get("bbox_width", 0.0))
                x_center = float(obj.get("x_center", 0.5))
                # If furniture/obstacle or any large object dead ahead
                if (label in OBSTACLE_LABELS and bbox_w > 0.28) or bbox_w > 0.42:
                    self._state = "TURN"
                    self._state_timer = now + random.uniform(0.5, 0.9)
                    self._turn_direction = -1 if x_center >= 0.5 else 1
                    context.controller.log_event("info", f"WanderMode: Visual obstacle '{label}' detected, steering away")
                    return DriveCommand(
                        left=self.cruise_speed * self._turn_direction,
                        right=-self.cruise_speed * self._turn_direction,
                    )

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
