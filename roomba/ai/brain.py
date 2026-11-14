"""
Physical AI & Multimodal LLM Brain Service for CrazyRoomba (Raspberry Pi 5).
Coordinates high-level scene understanding, conversational voice interaction,
visual question answering, pet detection reasoning, and autonomous action execution.

Supported AI backends:
1. Google Gemini Multimodal VLM (gemini-3.8-flash) via google-genai SDK (cloud / zero-load on Pi 5)
2. Local Ollama HTTP endpoint (local / LAN LLMs)
3. Built-in Deterministic Physical AI Agent (resilient local fallback with full offline operation)
"""

from __future__ import annotations

import os
import re
import time
import json
import base64
import asyncio
import inspect
import logging
from typing import Optional, Dict, Any, List, Tuple

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    httpx = None
    _HTTPX_AVAILABLE = False

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
        model_env = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
        # Upgrade deprecated models if requested
        if model_env.startswith(("gemini-2.5", "gemini-2.0", "gemini-1.5")):
            logger.info(f"Deprecated Gemini model '{model_env}' requested; upgrading to 'gemini-3.8-flash'")
            model_env = "gemini-3.8-flash"
        self.model: str = model_env

        self.ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3")
        self.ollama_vision_model: str = os.getenv("OLLAMA_VISION_MODEL", "llava")
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

    async def _call_gemini_generate_content(self, client: Any, contents: Any, config: Any) -> Any:
        """Call Gemini generate_content asynchronously using aio client or executor fallback."""
        aio_client = getattr(client, "aio", None)
        if aio_client is not None and hasattr(aio_client, "models"):
            res = aio_client.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            )
            if inspect.isawaitable(res):
                return await res
            if hasattr(res, "text") and isinstance(res.text, str):
                return res
            if hasattr(client, "models"):
                return await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: client.models.generate_content(
                        model=self.model,
                        contents=contents,
                        config=config,
                    ),
                )
            return res

        return await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: client.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            ),
        )

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
                    "any people, pets (especially cats and dogs), furniture, or open pathways, and give a recommendation."
                )
                contents = []
                if jpeg_bytes:
                    contents.append(genai_types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg"))
                contents.append(prompt)
                config_vlm = genai_types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2,
                    max_output_tokens=250,
                )

                response = await self._call_gemini_generate_content(client, contents, config_vlm)
                text = response.text.strip() if (response and hasattr(response, "text") and response.text) else "Scene analyzed."
                self._record_history(prompt, text, "scene_analysis", "gemini")
                return {
                    "ok": True,
                    "provider": "gemini",
                    "description": text,
                    "detected_objects": detected_objects,
                }
            except Exception as e:
                logger.warning(f"Gemini scene analysis error: {e}, falling back to local reasoning")

        # 2. Try Ollama local LLM / VLM if configured
        if self.provider == "ollama" and _HTTPX_AVAILABLE:
            try:
                images_b64 = [base64.b64encode(jpeg_bytes).decode("ascii")] if jpeg_bytes else []
                payload = {
                    "model": self.ollama_vision_model if images_b64 else self.ollama_model,
                    "prompt": (
                        f"You are CrazyRoomba, an intelligent autonomous Roomba robot with camera. "
                        f"{prompt}. Keep answer to 2-3 sentences."
                    ),
                    "stream": False,
                }
                if images_b64:
                    payload["images"] = images_b64
                async with httpx.AsyncClient(timeout=10.0) as http_client:
                    res = await http_client.post(f"{self.ollama_url}/api/generate", json=payload)
                    if res.status_code == 200:
                        data = res.json()
                        text = data.get("response", "").strip() or "Scene analyzed."
                        self._record_history(prompt, text, "scene_analysis", "ollama")
                        return {
                            "ok": True,
                            "provider": "ollama",
                            "description": text,
                            "detected_objects": detected_objects,
                        }
            except Exception as e:
                logger.warning(f"Ollama scene analysis error: {e}, falling back to local reasoning")

        # 3. Local Physical AI Scene Summarizer
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
                    f"You are the Physical AI Brain of CrazyRoomba, an autonomous Roomba 960 robot running Raspberry Pi 5. "
                    f"Telemetry: battery={telemetry.get('battery_percent', 0):.0f}%, mode={active_mode}, "
                    f"detected objects=[{labels_str}].\n"
                    f"User says: '{q_clean}'.\n"
                    f"Respond in 1-2 friendly sentences. If confirming or initiating a physical action, append an action tag "
                    f"at the end in brackets, e.g. [ACTION:mode_pet,species:cat], [ACTION:mode_pet,species:dog], "
                    f"[ACTION:mode_follow], [ACTION:mode_wander], [ACTION:stop], [ACTION:dock], [ACTION:clean], "
                    f"[ACTION:target_cat], [ACTION:target_dog], [ACTION:target_person], or [ACTION:none]."
                )

                config_ask = genai_types.GenerateContentConfig(temperature=0.3, max_output_tokens=150)
                response = await self._call_gemini_generate_content(client, [context_prompt], config_ask)

                if response and hasattr(response, "text") and response.text:
                    reply = response.text.strip()
                    used_provider = "gemini"
                    used_provider = "gemini"
            except Exception as e:
                logger.warning(f"Gemini text query failed: {e}, falling back to local intent reply")

        elif self.provider == "ollama" and _HTTPX_AVAILABLE:
            try:
                telemetry = getattr(self.controller, "latest_telemetry", {}) or {}
                active_mode = getattr(self.controller.mode_manager, "active_name", "manual") if self.controller else "manual"
                detected = vision.detected_objects if vision else []
                labels_str = ", ".join(f"{o['label']}({int(o['confidence']*100)}%)" for o in detected) if detected else "none"

                prompt = (
                    f"You are the Physical AI Brain of CrazyRoomba (Roomba 960 on Pi 5). "
                    f"Battery={telemetry.get('battery_percent', 0):.0f}%, mode={active_mode}, objects=[{labels_str}]. "
                    f"User: '{q_clean}'. Respond in 1-2 friendly sentences. "
                    f"Append action tag at the end in brackets if relevant: [ACTION:mode_pet,species:cat], "
                    f"[ACTION:mode_follow], [ACTION:mode_wander], [ACTION:stop], [ACTION:dock], or [ACTION:none]."
                )
                async with httpx.AsyncClient(timeout=10.0) as http_client:
                    res = await http_client.post(
                        f"{self.ollama_url}/api/generate",
                        json={"model": self.ollama_model, "prompt": prompt, "stream": False},
                    )
                    if res.status_code == 200:
                        data = res.json()
                        resp_txt = data.get("response", "").strip()
                        if resp_txt:
                            reply = resp_txt
                            used_provider = "ollama"
            except Exception as e:
                logger.warning(f"Ollama text query failed: {e}, falling back to local reasoning")

        # Step 3: Extract any [ACTION:...] tag from LLM response
        if reply:
            action_match = re.search(r"\[ACTION:\s*([a-zA-Z0-9_]+)(?:,\s*species:([a-zA-Z0-9_]+))?\]", reply)
            if action_match:
                parsed_intent = action_match.group(1).strip()
                if parsed_intent != "none":
                    if intent is None:
                        intent = parsed_intent
                        if action_match.group(2):
                            params["species"] = action_match.group(2).strip()
                reply = re.sub(r"\[ACTION:[^\]]+\]", "", reply).strip()

        # Step 4: Fallback local reply if neither Gemini nor Ollama responded
        if reply is None:
            reply = self._generate_local_reply(q_lower, intent)

        # Step 5: Execute robot action if requested
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
            "model": self.model if used_provider == "gemini" else (self.ollama_model if used_provider == "ollama" else "rule-based-physical-ai"),
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
        if re.search(r"\b(follow|track|find|look for|play with|companion|escort|watch)\b.*\b(dog|dogs|puppy|pup|canine)\b", t) or \
           any(k in t for k in ("follow dog", "track dog", "find dog", "dog companion", "play with dog")):
            return "mode_pet", {"species": "dog"}
        if re.search(r"\b(follow|track|find|look for|play with|companion|escort|watch)\b.*\b(cat|cats|kitten|kitty|feline)\b", t) or \
           any(k in t for k in ("follow cat", "track cat", "find cat", "cat companion", "play with cat", "pet mode", "pet companion", "follow pet", "look for cat", "cat mode", "kitten")):
            return "mode_pet", {"species": "cat"}

        # Target selection
        if any(k in t for k in ("target cat", "focus on cat", "switch to cat", "look for cat")):
            return "target_cat", {}
        if any(k in t for k in ("target dog", "focus on dog", "switch to dog", "look for dog")):
            return "target_dog", {}
        if any(k in t for k in ("target person", "focus on person", "focus on me", "target me", "target human")):
            return "target_person", {}
        if any(k in t for k in ("target any", "target all")):
            return "target_any", {}

        # Person follower mode
        if any(k in t for k in ("follow me", "follow person", "track me", "come with me")):
            return "mode_follow", {}

        # Wander / Explore
        if any(k in t for k in ("wander", "explore", "roam", "patrol", "scout", "look around room", "cruise", "avoid obstacles")):
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
        elif intent == "target_dog":
            return "Vision tracking target set to dog."
        elif intent == "target_person":
            return "Vision tracking target set to person."
        elif intent == "target_any":
            return "Vision tracking target set to any object."
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
            elif intent == "target_dog":
                if hasattr(c, "vision") and hasattr(c.vision, "set_target_class"):
                    c.vision.set_target_class("dog")
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
