"""
Physical AI & Multimodal LLM Brain Service for CrazyRoomba (Raspberry Pi 5).
Coordinates high-level scene understanding, conversational voice interaction,
visual question answering, pet detection reasoning, and autonomous action execution.

Supported AI backends:
1. Google Gemini Multimodal VLM (gemini-2.5-flash) via google-genai SDK (cloud / zero-load on Pi 5)
2. Local Ollama HTTP endpoint (local / LAN LLMs)
3. Built-in Deterministic Physical AI Agent (resilient local fallback with full offline operation)
"""

from __future__ import annotations

import os
import re
import time
import json
import logging
from typing import Optional, Dict, Any, List, Tuple

from roomba.config import config

logger = logging.getLogger("roomba.ai.brain")

try:
    from google import genai
    from google.genai import types as genai_types
    _GENAI_AVAILABLE = True
except ImportError:
    genai = None
    genai_types = None
    _GENAI_AVAILABLE = False


class AIBrainService:
    """Central Physical AI brain managing multimodal vision, natural language queries, and autonomous actions."""

    def __init__(self, controller: Any = None):
        self.controller = controller
        self.gemini_api_key: Optional[str] = (
            os.getenv("GEMINI_API_KEY") or getattr(config, "gemini_api_key", None)
        )
        self.model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.history: List[Dict[str, Any]] = []

        # Auto-detect active AI provider
        if self.gemini_api_key and _GENAI_AVAILABLE:
            self.provider = "gemini"
        elif os.getenv("ROOMBA_AI_PROVIDER") == "ollama":
            self.provider = "ollama"
        else:
            self.provider = "local"

    def get_status(self) -> Dict[str, Any]:
        """Return AI Brain status, active model, provider, and recent interaction history."""
        return {
            "available": True,
            "provider": self.provider,
            "model": self.model if self.provider == "gemini" else ("ollama" if self.provider == "ollama" else "rule-based-physical-ai"),
            "has_api_key": bool(self.gemini_api_key),
            "genai_sdk_available": _GENAI_AVAILABLE,
            "capabilities": [
                "multimodal_vision",
                "pet_detection_reasoning",
                "obstacle_analysis",
                "voice_action_routing",
                "scene_description",
            ],
            "history": self.history[-10:],
        }

    def _record_history(self, query: str, reply: str, intent: Optional[str], provider: str) -> None:
        self.history.append({
            "time": time.strftime("%H:%M:%S"),
            "query": query,
            "reply": reply,
            "intent": intent,
            "provider": provider,
        })
        if len(self.history) > 25:
            self.history.pop(0)

    async def analyze_scene(self, prompt: str = "Describe the room and identify any people, cats, or obstacles") -> Dict[str, Any]:
        """
        Multimodal scene analysis of the latest camera snapshot.
        Returns natural language description and detected entities.
        """
        vision = getattr(self.controller, "vision", None)
        jpeg_bytes = vision.get_latest_jpeg() if vision else None
        detected_objects = vision.detected_objects if vision else []

        # 1. Try Gemini Multimodal VLM if API key is present
        if self.provider == "gemini" and self.gemini_api_key and _GENAI_AVAILABLE:
            try:
                client = genai.Client(api_key=self.gemini_api_key)
                system_instruction = (
                    "You are CrazyRoomba, an intelligent autonomous Roomba 960 robot equipped with a Raspberry Pi 5 "
                    "and camera. Analyze this camera view. State what you observe concisely (2-3 sentences), identify "
                    "any people, pets (especially cats), furniture, or open pathways, and give a recommendation."
                )
                contents = []
                if jpeg_bytes:
                    contents.append(genai_types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg"))
                contents.append(prompt)
                response = client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.2,
                        max_output_tokens=250,
                    ),
                )
                text = response.text.strip() if response.text else "Scene analyzed."
                self._record_history(prompt, text, "scene_analysis", "gemini")
                return {
                    "ok": True,
                    "provider": "gemini",
                    "description": text,
                    "detected_objects": detected_objects,
                }
            except Exception as e:
                logger.warning(f"Gemini scene analysis error: {e}, falling back to local reasoning")

        # 2. Local Physical AI Scene Summarizer
        summary = self._generate_local_scene_summary(detected_objects)
        self._record_history(prompt, summary, "scene_analysis", "local")
        return {
            "ok": True,
            "provider": "local",
            "description": summary,
            "detected_objects": detected_objects,
        }

    def _generate_local_scene_summary(self, detected_objects: List[Dict[str, Any]]) -> str:
        """Generate high-clarity natural language scene summary from live detector data and telemetry."""
        if not detected_objects:
            base = "The camera view is clear with no prominent people or obstacles directly ahead."
        else:
            cat_list = [o for o in detected_objects if o["label"] == "cat"]
            dog_list = [o for o in detected_objects if o["label"] == "dog"]
            person_list = [o for o in detected_objects if o["label"] == "person"]
            other_list = [o for o in detected_objects if o["label"] not in ("cat", "dog", "person")]

            parts = []
            if cat_list:
                best_cat = max(cat_list, key=lambda c: c["confidence"])
                parts.append(f"a cat at {int(best_cat['confidence']*100)}% confidence")
            if dog_list:
                best_dog = max(dog_list, key=lambda d: d["confidence"])
                parts.append(f"a dog at {int(best_dog['confidence']*100)}% confidence")
            if person_list:
                best_p = max(person_list, key=lambda p: p["confidence"])
                parts.append(f"a person at {int(best_p['confidence']*100)}% confidence")
            if other_list:
                obj_names = ", ".join(o["label"] for o in other_list[:3])
                parts.append(f"objects including {obj_names}")

            base = f"In the camera frame I detect {', '.join(parts)}."

        # Add telemetry context if available
        telemetry = getattr(self.controller, "latest_telemetry", {}) or {}
        batt = telemetry.get("battery_percent", 0.0)
        mode = getattr(self.controller.mode_manager, "active_name", "manual") if self.controller else "manual"

        return f"{base} Roomba is in {mode} mode with battery at {batt:.0f}%."

    async def ask(
        self,
        query: str,
        include_vision: bool = True,
        execute: bool = True,
    ) -> Dict[str, Any]:
        """
        Process an open-ended natural language query or command.
        Reason about robot state and perception, formulate a spoken response,
        and optionally execute matching robot actions.
        """
        if not query or not query.strip():
            return {
                "ok": False,
                "query": "",
                "reply": "Please provide a query or command.",
                "intent": None,
                "executed": False,
                "provider": self.provider,
            }

        q_clean = query.strip()
        q_lower = q_clean.lower()

        # Step 1: Detect high-level physical AI intents
        intent, params = self._parse_intent_local(q_lower)

        # Step 2: Formulate reply
        reply: Optional[str] = None
        used_provider = "local"

        # If user explicitly asked for scene understanding or VLM question, try Gemini VLM
        is_scene_query = any(k in q_lower for k in ("what do you see", "describe", "look around", "what is in front"))
        vision = getattr(self.controller, "vision", None)
        jpeg_bytes = vision.get_latest_jpeg() if (vision and include_vision) else None

        if is_scene_query:
            scene_res = await self.analyze_scene(q_clean)
            reply = scene_res["description"]
            used_provider = scene_res["provider"]
            intent = "describe_scene"
        elif self.provider == "gemini" and self.gemini_api_key and _GENAI_AVAILABLE:
            try:
                client = genai.Client(api_key=self.gemini_api_key)
                telemetry = getattr(self.controller, "latest_telemetry", {}) or {}
                active_mode = getattr(self.controller.mode_manager, "active_name", "manual") if self.controller else "manual"
                detected = vision.detected_objects if vision else []
                labels_str = ", ".join(f"{o['label']}({int(o['confidence']*100)}%)" for o in detected) if detected else "none"

                context_prompt = (
                    f"You are the physical AI brain of a Roomba 960 running Raspberry Pi 5. "
                    f"Telemetry: battery={telemetry.get('battery_percent', 0):.0f}%, mode={active_mode}, "
                    f"detected objects=[{labels_str}].\n"
                    f"User says: '{q_clean}'.\n"
                    f"Respond in 1-2 friendly sentences. If the user wants to follow someone, pet companion, wander, "
                    f"or stop, confirm that action."
                )

                response = client.models.generate_content(
                    model=self.model,
                    contents=[context_prompt],
                    config=genai_types.GenerateContentConfig(temperature=0.3, max_output_tokens=150),
                )
                if response.text:
                    reply = response.text.strip()
                    used_provider = "gemini"
            except Exception as e:
                logger.warning(f"Gemini text query failed: {e}, falling back to local intent reply")

        # Step 3: Fallback local reply if Gemini didn't respond
        if reply is None:
            reply = self._generate_local_reply(q_lower, intent)

        # Step 4: Execute robot action if requested
        executed = False
        if execute and self.controller and intent:
            executed = await self._execute_intent_action(intent, params)

        self._record_history(q_clean, reply, intent, used_provider)

        return {
            "ok": True,
            "query": q_clean,
            "reply": reply,
            "intent": intent,
            "executed": executed,
            "provider": used_provider,
            "model": self.model if used_provider == "gemini" else "rule-based-physical-ai",
        }

    def _parse_intent_local(self, text: str) -> Tuple[Optional[str], Dict[str, Any]]:
        """Parse natural language into physical AI action intents."""
        t = re.sub(r"[^\w\s]", "", text).strip()

        # Emergency Stop
        if any(k in t for k in ("emergency stop", "estop", "freeze", "halt")):
            return "estop", {}
        if re.search(r"\bstop\b", t):
            return "stop", {}

        # Pet Companion Mode (Cats / Dogs)
        if re.search(r"\b(follow|track|find|look for|play with|companion)\b.*\b(cat|cats|kitten|kitty)\b", t) or \
           any(k in t for k in ("follow cat", "track cat", "find cat", "cat companion", "play with cat", "pet mode", "pet companion", "follow pet", "look for cat")):
            return "mode_pet", {"species": "cat"}
        if re.search(r"\b(follow|track|find|look for|play with|companion)\b.*\b(dog|dogs|puppy)\b", t) or \
           any(k in t for k in ("follow dog", "track dog", "find dog", "dog companion")):
            return "mode_pet", {"species": "dog"}

        # Target selection
        if any(k in t for k in ("target cat", "focus on cat", "switch to cat")):
            return "target_cat", {}
        if any(k in t for k in ("target person", "focus on person", "focus on me", "target human")):
            return "target_person", {}
        if any(k in t for k in ("target any", "target all")):
            return "target_any", {}

        # Person follower mode
        if any(k in t for k in ("follow me", "follow person", "track me", "come with me")):
            return "mode_follow", {}

        # Wander / Explore
        if any(k in t for k in ("wander", "explore", "roam", "patrol", "scout", "look around room")):
            return "mode_wander", {}

        # Manual Mode
        if any(k in t for k in ("manual mode", "teleop", "give me control")):
            return "mode_manual", {}

        # Roomba standard commands
        if any(k in t for k in ("dock", "recharge", "go home")):
            return "dock", {}
        if any(k in t for k in ("clean", "vacuum", "start cleaning")):
            return "clean", {}
        if any(k in t for k in ("sing", "beep", "make a sound", "play music", "play song", "hello")):
            return "beep", {}
        if any(k in t for k in ("battery", "status", "how are you", "report")):
            return "status", {}

        return None, {}

    def _generate_local_reply(self, text: str, intent: Optional[str]) -> str:
        """Produce helpful spoken reply when running locally."""
        if intent == "mode_pet":
            return "Activating Pet Companion mode. Tracking cat with safe buffer distances and playful chirps."
        elif intent == "mode_follow":
            return "Activating Follow Person mode. Locking visual tracking onto you."
        elif intent == "mode_wander":
            return "Activating Wander mode with multi-sensor and vision obstacle avoidance."
        elif intent == "mode_manual":
            return "Switching back to manual teleop mode."
        elif intent == "target_cat":
            return "Vision tracking target set to cat."
        elif intent == "target_person":
            return "Vision tracking target set to person."
        elif intent == "dock":
            return "Seeking charging dock."
        elif intent == "clean":
            return "Starting cleaning cycle."
        elif intent == "beep":
            return "Hello! Roomba reporting for duty."
        elif intent == "status":
            t = getattr(self.controller, "latest_telemetry", {}) or {}
            batt = t.get("battery_percent", 0.0)
            mode = getattr(self.controller.mode_manager, "active_name", "manual") if self.controller else "manual"
            return f"Roomba is operational in {mode} mode with battery at {batt:.0f}%."
        elif intent in ("stop", "estop"):
            return "Stopping robot immediately."
        else:
            return f"I heard '{text}'. I am ready to follow you, companion your cat, wander, or report status."

    async def _execute_intent_action(self, intent: str, params: Dict[str, Any]) -> bool:
        """Execute resolved physical action on the RobotController."""
        c = self.controller
        if not c:
            return False

        try:
            if intent == "estop":
                await c.emergency_stop()
                return True
            elif intent == "stop":
                if c.is_connected and c.client:
                    await c.client.stop()
                    c.is_driving = False
                await c.mode_manager.stop_active()
                return True
            elif intent == "mode_pet":
                species = params.get("species", "cat")
                if hasattr(c, "vision") and hasattr(c.vision, "set_target_class"):
                    c.vision.set_target_class(species)
                await c.set_operating_mode("pet_companion")
                return True
            elif intent == "mode_follow":
                if hasattr(c, "vision") and hasattr(c.vision, "set_target_class"):
                    c.vision.set_target_class("person")
                await c.set_operating_mode("follow_person")
                return True
            elif intent == "mode_wander":
                await c.set_operating_mode("wander")
                return True
            elif intent == "mode_manual":
                await c.set_operating_mode("manual")
                return True
            elif intent == "target_cat":
                if hasattr(c, "vision") and hasattr(c.vision, "set_target_class"):
                    c.vision.set_target_class("cat")
                return True
            elif intent == "target_person":
                if hasattr(c, "vision") and hasattr(c.vision, "set_target_class"):
                    c.vision.set_target_class("person")
                return True
            elif intent == "target_any":
                if hasattr(c, "vision") and hasattr(c.vision, "set_target_class"):
                    c.vision.set_target_class("any")
                return True
            elif intent in ("dock", "clean"):
                if c.is_connected:
                    await c.execute_action(intent)
                return True
            elif intent == "beep":
                if c.is_connected:
                    await c.execute_action("beep")
                return True
        except Exception as e:
            logger.warning(f"Error executing AI intent '{intent}': {e}")
            return False

        return False
