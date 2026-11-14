"""
AI Pet Companion Mode for Roomba 960.
Autonomous pet engagement mode designed to detect, track, and safely interact with cats and dogs.
Features safe buffer distances, playful back-up retreats when stalked by cats, and friendly audio chirps.
"""

from __future__ import annotations

import logging
import time
from typing import Optional, Dict, Any
from roomba.modes.base import BaseMode, RobotContext
from roomba.core.state import DriveCommand

logger = logging.getLogger("roomba.modes.pet_companion")


class PetCompanionMode(BaseMode):
    name: str = "pet_companion"
    description: str = "AI Pet Companion: detects & safely tracks cats/dogs with playful retreats"

    def __init__(
        self,
        target_species: str = "cat",
        safe_bbox_width: float = 0.26,     # Target distance: cats prefer more space than humans
        retreat_bbox_width: float = 0.38,  # If cat walks close, back away to invite playful stalking
        forward_speed: int = 120,          # Gentle cruise speed (do not scare pets!)
        turn_gain: float = 240.0,
        distance_gain: float = 300.0,
    ):
        super().__init__()
        self.target_species = target_species
        self.safe_bbox_width = safe_bbox_width
        self.retreat_bbox_width = retreat_bbox_width
        self.forward_speed = forward_speed
        self.turn_gain = turn_gain
        self.distance_gain = distance_gain

        self._last_seen_time = 0.0
        self._last_sound_time = 0.0
        self._search_direction = 1

    async def on_start(self, context: RobotContext) -> None:
        await super().on_start(context)
        self._last_seen_time = time.monotonic()
        self._last_sound_time = time.monotonic()
        if hasattr(context.controller, "vision") and hasattr(context.controller.vision, "set_target_class"):
            context.controller.vision.set_target_class(self.target_species)
        context.controller.log_event("info", f"PetCompanionMode: Activated. Looking for {self.target_species}...")

    async def update(self, context: RobotContext) -> Optional[DriveCommand]:
        now = time.monotonic()

        # Emergency obstacle protection: bumper or cliff
        if context.is_bumped or context.is_cliff_detected:
            context.controller.log_event("warn", "PetCompanion: Bump/cliff triggered, stopping safely")
            return DriveCommand.stop()

        # Proactive non-contact obstacle avoidance with IR Light Bumpers
        lb = context.telemetry.get("light_bumpers", {})
        front_blocked = lb.get("center_left") or lb.get("center_right")
        left_blocked = lb.get("front_left") or lb.get("left")
        right_blocked = lb.get("front_right") or lb.get("right")

        if front_blocked:
            return DriveCommand(left=-60, right=-60)
        elif left_blocked:
            return DriveCommand.spin_right(80)
        elif right_blocked:
            return DriveCommand.spin_left(80)

        # Check perception for pet target
        perception = context.perception or {}
        target = perception.get("target_cat")
        if not target or target.get("confidence", 0) < 0.20:
            target_obj = perception.get("target_object")
            if target_obj and target_obj.get("label") in ("cat", "dog"):
                target = target_obj

        # Fallback to any detected pet if specific target not set
        if not target and "detected_objects" in perception:
            for obj in perception["detected_objects"]:
                if obj.get("label") in ("cat", "dog") and obj.get("confidence", 0) > 0.20:
                    target = obj
                    break

        # 1. Pet is visible!
        if target and target.get("confidence", 0) > 0.15:
            self._last_seen_time = now
            x_center = float(target.get("x_center", 0.5))
            bbox_width = float(target.get("bbox_width", self.safe_bbox_width))

            # Playful audio cue: chirp periodically when engaged
            if now - self._last_sound_time > 10.0:
                self._last_sound_time = now
                try:
                    if hasattr(context.controller, "execute_action"):
                        await context.controller.execute_action("sound_mark", mark="happy")
                except Exception:
                    pass

            # Steering error
            steering_error = x_center - 0.5
            angular_velocity = int(steering_error * self.turn_gain)

            # Distance logic:
            # If pet comes too close (e.g. stalking the robot), back away playfully!
            if bbox_width > self.retreat_bbox_width:
                return DriveCommand(left=-70 + angular_velocity, right=-70 - angular_velocity).clamp()

            distance_error = self.safe_bbox_width - bbox_width
            linear_velocity = int(distance_error * self.distance_gain)
            linear_velocity = max(-70, min(self.forward_speed, linear_velocity))

            # Deadzone: sweet spot and centered
            if abs(distance_error) < 0.05 and abs(steering_error) < 0.08:
                return DriveCommand.stop()

            left_spd = linear_velocity + angular_velocity
            right_spd = linear_velocity - angular_velocity
            return DriveCommand(left=left_spd, right=right_spd).clamp()

        # 2. Lost target: Gentle search spin
        time_since_seen = now - self._last_seen_time
        if time_since_seen < 4.0:
            return DriveCommand.spin_right(60)

        # 3. Timeout: Stop and wait for pet
        return DriveCommand.stop()

    async def on_stop(self, context: RobotContext) -> None:
        await super().on_stop(context)
        if hasattr(context.controller, "vision") and hasattr(context.controller.vision, "set_target_class"):
            context.controller.vision.set_target_class("person")
        context.controller.log_event("info", "PetCompanionMode: Deactivated")
