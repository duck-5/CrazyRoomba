"""
English Voice Command Parser & Executor for Roomba 960.
Converts recognized English speech (from Pi mic, uploaded audio, or browser Web Speech API)
into safe Roomba controller actions and human-friendly TTS responses.
"""

from __future__ import annotations

import re
import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger("roomba.voice.commands")


def parse_voice_command(text: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Parse an English transcript into (intent, params).
    Returns (None, {}) if no known command matched.
    """
    if not text or not text.strip():
        return None, {}

    t = re.sub(r"[^\w\s]", "", text.lower()).strip()

    # Emergency / Stop (highest priority)
    if any(k in t for k in ("emergency stop", "e stop", "estop", "halt", "freeze")):
        return "estop", {}
    if re.search(r"\bstop\b", t):
        return "stop", {}

    # Arm / Disarm
    if "disarm" in t or "lock robot" in t or "lock motors" in t:
        return "disarm", {}
    if re.search(r"\barm\b", t):
        return "arm", {}

    # Autonomous Modes
    if any(k in t for k in ("follow cat", "track cat", "pet companion", "play with cat", "cat mode", "follow pet", "find cat")):
        return "mode_pet", {}
    if any(k in t for k in ("target cat", "look for cat")):
        return "target_cat", {}
    if any(k in t for k in ("target person", "target me")):
        return "target_person", {}
    if any(k in t for k in ("follow me", "follow person", "follow mode", "track me", "come with me")):
        return "mode_follow", {}
    if any(k in t for k in ("wander", "explore", "roam")):
        return "mode_wander", {}
    if "manual" in t:
        return "mode_manual", {}

    # Motion nudges
    if any(k in t for k in ("forward", "ahead", "straight")):
        return "move_forward", {}
    if any(k in t for k in ("backward", "back up", "reverse", "go back")):
        return "move_backward", {}
    if "left" in t:
        return "turn_left", {}
    if "right" in t:
        return "turn_right", {}

    # Special Roomba OI actions
    if any(k in t for k in ("dock", "go home", "charge")):
        return "dock", {}
    if "clean" in t:
        return "clean", {}
    if "spot" in t:
        return "spot", {}
    if any(k in t for k in ("beep", "sing", "hello", "hi roomba")):
        return "beep", {}

    # Status / Battery query
    if any(k in t for k in ("status", "battery", "how are you", "report")):
        return "status", {}

    return None, {}


async def execute_voice_command(controller: Any, text: str) -> Dict[str, Any]:
    """
    Parse and execute an English voice command against RobotController.
    Returns structured result with `recognized`, `intent`, `executed`, and `reply`.
    """
    intent, _ = parse_voice_command(text)
    if intent is None:
        return {
            "recognized": False,
            "intent": None,
            "executed": False,
            "reply": f"Sorry, I did not understand the command: {text}",
        }

    if controller is None:
        return {
            "recognized": True,
            "intent": intent,
            "executed": False,
            "reply": f"Recognized '{intent}', but robot controller is unavailable.",
        }

    try:
        if intent == "estop":
            await controller.emergency_stop()
            return {"recognized": True, "intent": intent, "executed": True, "reply": "Emergency stop activated. Motors halted and disarmed."}

        if intent == "stop":
            if controller.is_connected and controller.client:
                await controller.client.stop()
                controller.is_driving = False
            await controller.mode_manager.stop_active()
            return {"recognized": True, "intent": intent, "executed": True, "reply": "Stopping robot."}

        if intent == "arm":
            if not controller.is_connected:
                return {"recognized": True, "intent": intent, "executed": False, "reply": "Cannot arm. Roomba is not connected."}
            controller.arm()
            return {"recognized": True, "intent": intent, "executed": True, "reply": "Robot armed and ready."}

        if intent == "disarm":
            controller.disarm()
            return {"recognized": True, "intent": intent, "executed": True, "reply": "Robot disarmed."}

        if intent == "mode_pet":
            if hasattr(controller, "vision") and hasattr(controller.vision, "set_target_class"):
                controller.vision.set_target_class("cat")
            await controller.set_operating_mode("pet_companion")
            return {"recognized": True, "intent": intent, "executed": True, "reply": "Switching to pet companion mode."}

        if intent == "target_cat":
            if hasattr(controller, "vision") and hasattr(controller.vision, "set_target_class"):
                controller.vision.set_target_class("cat")
            return {"recognized": True, "intent": intent, "executed": True, "reply": "Vision target set to cat."}

        if intent == "target_person":
            if hasattr(controller, "vision") and hasattr(controller.vision, "set_target_class"):
                controller.vision.set_target_class("person")
            return {"recognized": True, "intent": intent, "executed": True, "reply": "Vision target set to person."}

        if intent == "mode_follow":
            if hasattr(controller, "vision") and hasattr(controller.vision, "set_target_class"):
                controller.vision.set_target_class("person")
            await controller.set_operating_mode("follow_person")
            return {"recognized": True, "intent": intent, "executed": True, "reply": "Switching to follow person mode."}

        if intent == "mode_wander":
            await controller.set_operating_mode("wander")
            return {"recognized": True, "intent": intent, "executed": True, "reply": "Switching to wander mode."}

        if intent == "mode_manual":
            await controller.set_operating_mode("manual")
            return {"recognized": True, "intent": intent, "executed": True, "reply": "Switching to manual mode."}

        if intent in ("move_forward", "move_backward", "turn_left", "turn_right"):
            if not controller.is_connected:
                return {"recognized": True, "intent": intent, "executed": False, "reply": "Cannot move. Roomba is not connected."}
            if not controller.armed:
                return {"recognized": True, "intent": intent, "executed": False, "reply": "Cannot move. Robot is disarmed. Say arm first."}
            if intent == "move_forward":
                await controller.nudge(150, 150, 0.5)
                return {"recognized": True, "intent": intent, "executed": True, "reply": "Moving forward."}
            if intent == "move_backward":
                await controller.nudge(-150, -150, 0.5)
                return {"recognized": True, "intent": intent, "executed": True, "reply": "Moving backward."}
            if intent == "turn_left":
                await controller.nudge(-150, 150, 0.45)
                return {"recognized": True, "intent": intent, "executed": True, "reply": "Turning left."}
            if intent == "turn_right":
                await controller.nudge(150, -150, 0.45)
                return {"recognized": True, "intent": intent, "executed": True, "reply": "Turning right."}

        if intent in ("dock", "clean", "spot"):
            if not controller.is_connected:
                return {"recognized": True, "intent": intent, "executed": False, "reply": f"Cannot {intent}. Roomba is not connected."}
            await controller.execute_action(intent)
            return {"recognized": True, "intent": intent, "executed": True, "reply": f"Executing {intent}."}

        if intent == "beep":
            if controller.is_connected:
                await controller.execute_action("beep")
            return {"recognized": True, "intent": intent, "executed": True, "reply": "Hello! Roomba reporting for duty."}

        if intent == "status":
            t = controller.latest_telemetry or {}
            if not controller.is_connected:
                return {"recognized": True, "intent": intent, "executed": True, "reply": "Roomba is currently disconnected."}
            batt = t.get("battery_percent", 0)
            mode = controller.mode_manager.active_name
            armed_str = "armed" if controller.armed else "disarmed"
            return {
                "recognized": True,
                "intent": intent,
                "executed": True,
                "reply": f"Roomba is connected, {armed_str}, in {mode} mode, battery at {batt:.0f} percent.",
            }

    except Exception as e:
        logger.warning(f"Voice command '{intent}' execution error: {e}")
        return {
            "recognized": True,
            "intent": intent,
            "executed": False,
            "reply": f"Command failed: {e}",
        }

    return {"recognized": False, "intent": None, "executed": False, "reply": "Command not handled."}
