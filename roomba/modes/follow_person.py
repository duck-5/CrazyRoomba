"""
Vision-Based Person Follower Mode (Architecture Template).
Demonstrates how camera perception data (bounding boxes) seamlessly drives the Roomba.
Ready for OpenCV / YOLO / MobileNet / MediaPipe detection pipelines on Raspberry Pi.
"""

from __future__ import annotations

import logging
import time
from typing import Optional, Dict, Any
from roomba.modes.base import BaseMode, RobotContext
from roomba.core.state import DriveCommand

logger = logging.getLogger("roomba.modes.follow_person")


class FollowPersonMode(BaseMode):
    name: str = "follow_person"
    description: str = "Vision-guided person tracking and following (camera perception ready)"

    def __init__(
        self,
        target_bbox_width: float = 0.35,  # Desired fraction of frame width for person distance
        forward_speed: int = 150,
        turn_gain: float = 300.0,         # Gain for steering toward center
        distance_gain: float = 400.0,     # Gain for forward/backward throttle
    ):
        super().__init__()
        self.target_bbox_width = target_bbox_width
        self.forward_speed = forward_speed
        self.turn_gain = turn_gain
        self.distance_gain = distance_gain

        self._last_seen_time = 0.0
        self._search_direction = 1

    async def on_start(self, context: RobotContext) -> None:
        await super().on_start(context)
        self._last_seen_time = time.monotonic()
        context.controller.log_event("info", "FollowPersonMode: Activated. Looking for target...")

    async def update(self, context: RobotContext) -> Optional[DriveCommand]:
        """
        Process perception data and compute steering / throttle.
        Expected perception payload format:
          context.perception['target_person'] = {
              'x_center': 0.5,      # Normalized horizontal position: 0.0 (left) to 1.0 (right)
              'bbox_width': 0.3,    # Normalized bounding box width
              'confidence': 0.85,   # Detection confidence
          }
        """
        now = time.monotonic()

        # Emergency obstacle protection: if robot bumpers or cliffs fire, halt
        if context.is_bumped or context.is_cliff_detected:
            context.controller.log_event("warn", "FollowPerson: Safety sensor triggered, stopping")
            return DriveCommand.stop()

        target = context.perception.get("target_person")

        # 1. Target is visible
        if target and target.get("confidence", 0) > 0.4:
            self._last_seen_time = now
            x_center = float(target.get("x_center", 0.5))  # 0.0 left, 0.5 center, 1.0 right
            bbox_width = float(target.get("bbox_width", self.target_bbox_width))

            # Steering error (-0.5 to +0.5)
            # Negative = target to the left, Positive = target to the right
            steering_error = x_center - 0.5
            angular_velocity = int(steering_error * self.turn_gain)

            # Distance error: if bbox is too small, person is too far -> drive forward
            distance_error = self.target_bbox_width - bbox_width
            linear_velocity = int(distance_error * self.distance_gain)
            linear_velocity = max(-100, min(self.forward_speed, linear_velocity))

            # Deadzone: if close enough and centered, stay stopped
            if abs(distance_error) < 0.05 and abs(steering_error) < 0.08:
                return DriveCommand.stop()

            # Differential drive mixing
            left_spd = linear_velocity + angular_velocity
            right_spd = linear_velocity - angular_velocity

            return DriveCommand(left=left_spd, right=right_spd).clamp()

        # 2. Target lost: Search routine if lost recently
        time_since_seen = now - self._last_seen_time
        if time_since_seen < 4.0:
            # Gentle spin search in last known direction
            return DriveCommand.spin_right(80)

        # 3. Timeout: Stop and wait for target to reappear
        return DriveCommand.stop()

    async def on_stop(self, context: RobotContext) -> None:
        await super().on_stop(context)
        context.controller.log_event("info", "FollowPersonMode: Deactivated")


# Backward-compatible alias
FollowPersonBehavior = FollowPersonMode
