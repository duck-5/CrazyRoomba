"""
Central Robot Controller and Coordinator.
Manages serial connection lifecycle, telemetry streaming, ARM/DISARM safety,
deadman watchdog, WebSocket broadcasting, and behavior manager arbitration.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional, Dict, Any, Set, List
from fastapi import WebSocket

from roomba.driver.client import RoombaClient
from roomba.driver.mock import MockRoombaClient
from roomba.driver.discovery import find_roomba_port
from roomba.driver.sound import (
    PRESET_TUNES,
    RTTTL_SAMPLES,
    HUMAN_SOUNDS,
    rtttl_to_notes,
    text_to_morse_notes,
    text_to_vocal_tones,
    grind_audio_to_roomba_notes,
    grind_wav_bytes_to_notes,
    synthesize_and_grind_speech,
)
from roomba.modes.manager import ModeManager
from roomba.modes.manual import ManualMode
from roomba.modes.wander import WanderMode
from roomba.modes.follow_person import FollowPersonMode
from roomba.config import config

logger = logging.getLogger("roomba.core.controller")


class RobotController:
    """Central coordinator for Roomba operations, safety, operating modes, and telemetry streaming."""

    def __init__(self, default_mode: str = "Safe", deadman_timeout: Optional[float] = None):
        self.default_mode = default_mode
        self.deadman_timeout = deadman_timeout or config.deadman_timeout

        self.client: Optional[RoombaClient | MockRoombaClient] = None
        self.is_mock: bool = False
        self.port: Optional[str] = None

        # Safety & Arming State
        self.armed: bool = False
        self.is_driving: bool = False
        self.last_drive_time: float = 0.0

        # Background Tasks & Subscriptions
        self._telemetry_task: Optional[asyncio.Task] = None
        self._watchdog_task: Optional[asyncio.Task] = None
        self._subscribers: Set[WebSocket] = set()

        # Operating Mode Manager (with behavior_manager backward-compatibility alias)
        self.mode_manager = ModeManager(self)
        self.behavior_manager = self.mode_manager
        self._init_modes()

        # Cached latest telemetry snapshot & perceptions
        self.latest_telemetry: Dict[str, Any] = self._empty_telemetry()
        self.latest_perception: Dict[str, Any] = {}
        self.event_log: list[Dict[str, Any]] = []

    def _init_modes(self) -> None:
        """Register autonomous operating mode scripts."""
        self.mode_manager.register(WanderMode(cruise_speed=150))
        self.mode_manager.register(FollowPersonMode(forward_speed=150))

    def _init_behaviors(self) -> None:
        """Backward-compatible alias for _init_modes."""
        self._init_modes()

    def _empty_telemetry(self) -> Dict[str, Any]:
        return {
            "connected": False,
            "port": None,
            "is_mock": False,
            "armed": False,
            "is_driving": False,
            "mode": "Off",
            "oi_mode": "Off",
            "active_behavior": self.behavior_manager.active_name,
            "voltage_v": 0.0,
            "voltage_mv": 0,
            "current_ma": 0,
            "battery_charge_mah": 0,
            "battery_capacity_mah": 0,
            "battery_percent": 0.0,
            "temperature_c": 0,
            "charging_state": "Unknown",
            "charging_state_code": 0,
            "bumps_and_drops": {
                "bump_right": False,
                "bump_left": False,
                "wheel_drop_right": False,
                "wheel_drop_left": False,
            },
            "cliffs": {
                "cliff_left": False,
                "cliff_front_left": False,
                "cliff_front_right": False,
                "cliff_right": False,
            },
            "wall": {
                "wall": False,
                "virtual_wall": False,
            },
            "light_bumpers": {
                "left": False,
                "front_left": False,
                "center_left": False,
                "center_right": False,
                "front_right": False,
                "right": False,
            },
            "encoders": {
                "left": 0,
                "right": 0,
                "distance_mm": 0,
                "angle_deg": 0,
            },
            "velocities": {
                "left": 0,
                "right": 0,
            },
            "timestamp": time.time(),
        }

    def log_event(self, level: str, message: str) -> None:
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message,
        }
        self.event_log.append(entry)
        if len(self.event_log) > 100:
            self.event_log.pop(0)
        logger.info(f"[{level.upper()}] {message}")

    @property
    def is_connected(self) -> bool:
        return self.client is not None and self.client.is_connected

    # --- Connection Management ---

    async def connect(self, port: Optional[str] = None, mock: bool = False) -> Dict[str, Any]:
        """Connect to Roomba serial hardware or start mock simulation."""
        if self.is_connected:
            await self.disconnect()

        self.is_mock = mock

        if mock:
            self.port = "MOCK_SIMULATOR"
            self.client = MockRoombaClient(port=self.port)
            await self.client.connect()
            self.log_event("info", "Connected to Mock Roomba Simulator")
        else:
            target_port = port or find_roomba_port()
            if not target_port:
                raise ConnectionError("No Roomba serial port detected. Specify port or use Mock mode.")
            self.port = target_port
            self.client = RoombaClient(port=target_port, baudrate=config.baudrate, timeout=config.serial_timeout)
            try:
                await self.client.connect()
                self.log_event("success", f"Serial connection opened on {target_port}")
            except Exception as e:
                self.client = None
                self.port = None
                self.log_event("error", f"Connection failed on {target_port}: {e}")
                raise

        # Initialize OI mode
        if self.default_mode.lower() == "full":
            await self.client.full_mode()
        else:
            await self.client.safe_mode()

        self.log_event("info", f"Initialized Roomba mode: {self.client.mode}")

        # Start loops
        self._start_background_tasks()
        self.behavior_manager.start_loop(rate_hz=config.behavior_rate_hz)

        # Initial telemetry snapshot
        try:
            telemetry = await self.client.get_telemetry()
            self._enrich_telemetry(telemetry)
            self.latest_telemetry = telemetry
        except Exception as e:
            logger.warning(f"Initial telemetry query warning: {e}")

        return {"status": "connected", "port": self.port, "is_mock": self.is_mock, "mode": self.client.mode}

    async def disconnect(self) -> Dict[str, Any]:
        """Safely disarm, stop motors, and close serial port."""
        self.disarm()
        self._stop_background_tasks()
        self.behavior_manager.stop_loop()

        if self.client:
            old_port = self.port
            try:
                await self.client.stop()
                await self.client.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting: {e}")
            self.client = None
            self.port = None
            self.is_mock = False
            self.log_event("info", f"Disconnected from {old_port}")

        self.latest_telemetry = self._empty_telemetry()
        await self._broadcast_telemetry(self.latest_telemetry)
        return {"status": "disconnected"}

    # --- Safety & Arming Controls ---

    def arm(self) -> Dict[str, Any]:
        """Arm the robot to allow motion commands."""
        if not self.is_connected:
            raise RuntimeError("Cannot arm: Roomba is not connected.")

        self.armed = True
        self.last_drive_time = time.monotonic()
        self.log_event("warn", "ROBOT ARMED - Motion controls ACTIVE")
        return {"armed": True}

    def disarm(self) -> Dict[str, Any]:
        """Disarm the robot and halt all motor motion immediately."""
        self.armed = False
        self.is_driving = False
        if self.is_connected and self.client:
            asyncio.create_task(self._safe_stop_motors())
        self.log_event("info", "Robot DISARMED - Motion controls LOCKED")
        return {"armed": False}

    async def emergency_stop(self) -> Dict[str, Any]:
        """E-STOP: Immediately halt motors, revert to manual behavior, and disarm."""
        self.armed = False
        self.is_driving = False
        await self.behavior_manager.stop_active()
        if self.is_connected and self.client:
            try:
                await self.client.stop()
            except Exception as e:
                logger.error(f"E-STOP stop error: {e}")
        self.log_event("critical", "EMERGENCY STOP ACTIVATED! Motors halted.")
        return {"status": "estopped", "armed": False}

    async def _safe_stop_motors(self) -> None:
        try:
            if self.client:
                await self.client.stop()
        except Exception as e:
            logger.debug(f"Stop motors error: {e}")

    # --- Mode & Behavior Management ---

    async def set_mode(self, mode: str) -> Dict[str, Any]:
        """Set Roomba OI mode: safe, full, passive, off."""
        if not self.is_connected or not self.client:
            raise RuntimeError("Cannot change mode: Roomba is not connected.")

        mode_lower = mode.lower()
        if mode_lower == "safe":
            await self.client.safe_mode()
        elif mode_lower == "full":
            await self.client.full_mode()
        elif mode_lower == "passive":
            self.disarm()
            await self.client.start()
        elif mode_lower in ("off", "stop"):
            self.disarm()
            await self.client.stop_oi()
        else:
            raise ValueError(f"Unknown mode: {mode}. Supported modes: safe, full, passive, off")

        self.log_event("info", f"Switched mode to {self.client.mode}")
        return {"status": "ok", "mode": self.client.mode, "armed": self.armed}

    async def set_operating_mode(self, mode_name: str) -> Dict[str, Any]:
        """Switch active autonomous operating mode (e.g. manual, wander, follow_person)."""
        await self.mode_manager.set_active(mode_name)
        return {
            "status": "ok",
            "active_mode": self.mode_manager.active_name,
            "active_behavior": self.mode_manager.active_name,
        }

    async def set_behavior(self, behavior_name: str) -> Dict[str, Any]:
        """Backward-compatible alias for set_operating_mode."""
        return await self.set_operating_mode(behavior_name)

    def list_modes(self) -> List[Dict[str, Any]]:
        """List all available operating mode scripts."""
        return self.mode_manager.list_modes()

    def list_behaviors(self) -> List[Dict[str, Any]]:
        """Backward-compatible alias for list_modes."""
        return self.list_modes()

    def set_perception_target(self, target_data: Dict[str, Any]) -> None:
        """Inject target perception data (e.g. vision bounding box) for autonomous modes."""
        self.latest_perception = target_data

    # --- Movement Commands ---

    async def drive(self, left_speed_mm_s: int, right_speed_mm_s: int) -> Dict[str, Any]:
        """Direct wheel speed drive. Requires ARMED state."""
        if not self.is_connected or not self.client:
            raise RuntimeError("Roomba is not connected.")

        if not self.armed:
            raise RuntimeError("Robot is DISARMED! Arm robot before driving.")

        if left_speed_mm_s == 0 and right_speed_mm_s == 0:
            await self.client.stop()
            self.is_driving = False
            return {"status": "stopped", "left": 0, "right": 0}

        await self.client.drive_direct(right_speed_mm_s, left_speed_mm_s)
        self.is_driving = True
        self.last_drive_time = time.monotonic()
        return {"status": "driving", "left": left_speed_mm_s, "right": right_speed_mm_s}

    async def nudge(self, left_speed: int, right_speed: int, duration_s: float = 0.5) -> Dict[str, Any]:
        """Drive for a discrete duration and automatically halt."""
        if not self.is_connected or not self.client:
            raise RuntimeError("Roomba is not connected.")

        if not self.armed:
            raise RuntimeError("Robot is DISARMED! Arm robot before driving.")

        self.is_driving = True
        self.last_drive_time = time.monotonic()
        try:
            await self.client.move_wheel(
                right_speed_mm_s=right_speed,
                left_speed_mm_s=left_speed,
                duration_s=duration_s,
            )
        finally:
            self.is_driving = False
        return {"status": "completed", "left": left_speed, "right": right_speed, "duration_s": duration_s}

    async def execute_action(self, action: str, **kwargs) -> Dict[str, Any]:
        if not self.is_connected or not self.client:
            raise RuntimeError("Roomba is not connected.")

        act = action.lower()
        if act == "beep":
            raw_note = kwargs.get("note")
            note = int(raw_note) if raw_note is not None else 72
            raw_dur = kwargs.get("duration")
            duration = int(raw_dur) if raw_dur is not None else 16
            await self.client.beep(note, duration)
            self.log_event("info", f"Triggered Beep (MIDI note {note})")
            return {"status": "ok", "action": "beep", "note": note, "duration": duration}

        elif act == "tune":
            preset = str(kwargs.get("preset", "mario")).lower()
            if preset not in PRESET_TUNES:
                raise ValueError(f"Unknown preset tune: '{preset}'. Available: {list(PRESET_TUNES.keys())}")
            notes = PRESET_TUNES[preset]
            await self.client.play_tune(notes)
            self.log_event("info", f"Played Preset Tune '{preset}' ({len(notes)} notes)")
            return {"status": "ok", "action": "tune", "preset": preset, "notes_count": len(notes)}

        elif act == "song":
            raw_notes = kwargs.get("notes", [])
            notes = [(int(n[0]), int(n[1])) for n in raw_notes]
            if not notes:
                raise ValueError("Notes list cannot be empty")
            await self.client.play_tune(notes)
            self.log_event("info", f"Played custom song ({len(notes)} notes)")
            return {"status": "ok", "action": "song", "notes_count": len(notes)}

        elif act == "rtttl":
            rtttl_str = str(kwargs.get("rtttl", "")).strip()
            if not rtttl_str:
                raise ValueError("RTTTL string cannot be empty")
            notes = rtttl_to_notes(rtttl_str)
            await self.client.play_tune(notes)
            self.log_event("info", f"Played RTTTL tune ({len(notes)} notes)")
            return {"status": "ok", "action": "rtttl", "notes_count": len(notes)}

        elif act == "morse":
            text = str(kwargs.get("text", "")).strip()
            if not text:
                raise ValueError("Text for Morse code cannot be empty")
            raw_note = kwargs.get("note")
            note = int(raw_note) if raw_note is not None else 76
            raw_dot = kwargs.get("dot_duration")
            dot_dur = int(raw_dot) if raw_dot is not None else 6
            notes = text_to_morse_notes(text, note=note, dot_duration=dot_dur)
            await self.client.play_tune(notes)
            self.log_event("info", f"Transmitted Morse audio for: '{text}' ({len(notes)} tones/gaps)")
            return {"status": "ok", "action": "morse", "text": text, "notes_count": len(notes)}

        elif act == "sos":
            text = "SOS"
            raw_note = kwargs.get("note")
            note = int(raw_note) if raw_note is not None else 76
            raw_dot = kwargs.get("dot_duration")
            dot_dur = int(raw_dot) if raw_dot is not None else 6
            notes = text_to_morse_notes(text, note=note, dot_duration=dot_dur)
            await self.client.play_tune(notes)
            self.log_event("info", f"Transmitted SOS emergency signal ({len(notes)} tones/gaps)")
            return {"status": "ok", "action": "sos", "text": "SOS", "notes_count": len(notes)}

        elif act in ("human", "vocal", "voice", "speak", "speak_roomba"):
            sound_name = str(kwargs.get("sound", kwargs.get("preset", "hello"))).lower()
            if sound_name in HUMAN_SOUNDS:
                notes = HUMAN_SOUNDS[sound_name]
                await self.client.play_tune(notes)
                self.log_event("info", f"Played Human Vocal Sound '{sound_name}' ({len(notes)} notes)")
                return {"status": "ok", "action": act, "sound": sound_name, "notes_count": len(notes)}
            else:
                text = str(kwargs.get("text", sound_name))
                mode = str(kwargs.get("mode", "formant_interleave"))
                try:
                    notes = synthesize_and_grind_speech(text, mode=mode)
                except Exception as e:
                    logger.warning(f"Error in synthesize_and_grind_speech: {e}")
                    notes = text_to_vocal_tones(text)
                if not notes:
                    notes = text_to_vocal_tones(text)
                if notes:
                    await self.client.play_tune(notes)
                self.log_event("info", f"Ground and played Human Voice for '{text}' ({len(notes)} notes)")
                return {"status": "ok", "action": act, "text": text, "notes_count": len(notes)}

        elif act in ("grind_audio", "audio_grind"):
            import base64
            audio_b64 = kwargs.get("audio_base64")
            wav_bytes = kwargs.get("wav_bytes")
            if audio_b64 and not wav_bytes:
                wav_bytes = base64.b64decode(audio_b64)
            if not wav_bytes:
                raise ValueError("No audio payload provided for grind_audio")
            mode = str(kwargs.get("mode", "formant_interleave"))
            notes = grind_wav_bytes_to_notes(wav_bytes, mode=mode)
            if notes:
                await self.client.play_tune(notes)
            dur_s = sum(d for _, d in notes) / 64.0 if notes else 0.0
            self.log_event("info", f"Ground audio signal into {len(notes)} Roomba notes ({dur_s:.2f}s)")
            return {"status": "ok", "action": "grind_audio", "notes_count": len(notes), "duration_s": dur_s}


        elif act == "clean":
            self.disarm()
            await self.client.clean()
            self.log_event("info", "Triggered Clean cycle")
            return {"status": "ok", "action": "clean"}

        elif act == "spot":
            self.disarm()
            await self.client.spot()
            self.log_event("info", "Triggered Spot Clean")
            return {"status": "ok", "action": "spot"}

        elif act == "dock":
            self.disarm()
            await self.client.seek_dock()
            self.log_event("info", "Triggered Seek Dock")
            return {"status": "ok", "action": "dock"}

        elif act == "mock_sensor" and self.is_mock and isinstance(self.client, MockRoombaClient):
            sensor = kwargs.get("sensor")
            value = kwargs.get("value")
            self.client.set_sensor(sensor, value)
            self.log_event("info", f"Mock Sensor Set: {sensor} = {value}")
            return {"status": "ok", "sensor": sensor, "value": value}

        elif act == "reset_odometry":
            return self.reset_odometry()

        else:
            raise ValueError(f"Unsupported action: {action}")

    def reset_odometry(self) -> Dict[str, Any]:
        """Reset cumulative odometry distance and angle to zero."""
        if self.client and hasattr(self.client, "reset_odometry"):
            self.client.reset_odometry()
        self.log_event("info", "Odometry reset to zero")
        return {"status": "ok", "action": "reset_odometry"}

    def get_sound_presets(self) -> Dict[str, Any]:
        """Return available preset tunes, human sounds, and sample RTTTL ringtone strings."""
        return {
            "presets": list(PRESET_TUNES.keys()),
            "human_sounds": list(HUMAN_SOUNDS.keys()),
            "rtttl_samples": {
                "Mario": "mario:d=4,o=5,b=100:16e6,16e6,32p,8e6,16c6,8e6,8g6,8p,8g",
                "Imperial March": "imperial:d=4,o=5,b=100:e,e,e,8c,16g,e,8c,16g,2e",
                "Mission Impossible": "mission:d=4,o=6,b=150:16d,16d#,16d,16d#,16d,16d#,16d,16d#,16d,16d,16d#,16e,16f,16f#,16g,8g.,8p,8g.,8p,8a#.,8p,8c7.,8p",
                "Zelda Secret": "zelda:d=4,o=5,b=125:8g,8f#,8d#,8a4,8g#4,8e,8g#,2c6"
            }
        }

    # --- Background Telemetry & Watchdog ---

    def _start_background_tasks(self) -> None:
        self._stop_background_tasks()
        self._telemetry_task = asyncio.create_task(self._telemetry_loop())
        self._watchdog_task = asyncio.create_task(self._deadman_watchdog_loop())

    def _stop_background_tasks(self) -> None:
        if self._telemetry_task and not self._telemetry_task.done():
            self._telemetry_task.cancel()
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
        self._telemetry_task = None
        self._watchdog_task = None

    async def _telemetry_loop(self) -> None:
        interval = config.telemetry_interval
        logger.info(f"Telemetry streaming loop started at {config.telemetry_rate_hz} Hz")
        while self.is_connected and self.client:
            try:
                t = await self.client.get_telemetry()
                self._enrich_telemetry(t)
                self.latest_telemetry = t
                await self._broadcast_telemetry(t)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Telemetry loop read error: {e}")

            await asyncio.sleep(interval)

    async def _deadman_watchdog_loop(self) -> None:
        # Only enforces deadman for manual teleoperation (autonomous behaviors run continuously)
        while self.is_connected and self.client:
            try:
                if self.is_driving and self.behavior_manager.active_name == "manual":
                    elapsed = time.monotonic() - self.last_drive_time
                    if elapsed > self.deadman_timeout:
                        logger.debug("Deadman timeout reached: stopping motors")
                        await self.client.stop()
                        self.is_driving = False
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Watchdog error: {e}")

            await asyncio.sleep(0.1)

    def _enrich_telemetry(self, t: Dict[str, Any]) -> None:
        t["armed"] = self.armed
        t["is_driving"] = self.is_driving
        t["is_mock"] = self.is_mock
        t["port"] = self.port
        t["active_mode"] = self.mode_manager.active_name
        t["active_behavior"] = self.behavior_manager.active_name
        t["timestamp"] = time.time()

    # --- WebSocket Broadcasting ---

    def register_subscriber(self, ws: WebSocket) -> None:
        self._subscribers.add(ws)

    def unregister_subscriber(self, ws: WebSocket) -> None:
        self._subscribers.discard(ws)

    async def _broadcast_telemetry(self, data: Dict[str, Any]) -> None:
        if not self._subscribers:
            return

        dead_subscribers = []
        for ws in self._subscribers:
            try:
                await ws.send_json(data)
            except Exception:
                dead_subscribers.append(ws)

        for ws in dead_subscribers:
            self._subscribers.discard(ws)
