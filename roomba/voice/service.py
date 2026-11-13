"""
Unified English Voice Service (TTS + STT + Voice Command Execution) for Roomba 960.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from roomba.voice.tts import TTSEngine
from roomba.voice.stt import STTEngine
from roomba.voice.commands import execute_voice_command


class VoiceService:
    """Coordinates English TTS, STT, hardware probing, and Roomba voice commands."""

    def __init__(self, controller: Any = None):
        self.controller = controller
        self.tts = TTSEngine()
        self.stt = STTEngine()
        self.history: List[Dict[str, Any]] = []

    def _record_history(self, kind: str, text: str, meta: Optional[Dict[str, Any]] = None) -> None:
        self.history.append({
            "time": time.strftime("%H:%M:%S"),
            "type": kind,
            "text": text,
            **(meta or {}),
        })
        if len(self.history) > 30:
            self.history.pop(0)

    def get_status(self) -> Dict[str, Any]:
        return {
            "tts": self.tts.get_status(),
            "stt": self.stt.get_status(),
            "history": self.history[-15:],
        }

    def retry(self) -> Dict[str, Any]:
        """Re-probe speaker & microphone hardware and local engines."""
        self.tts.probe()
        self.stt.probe()
        if self.controller:
            self.controller.log_event(
                "info",
                f"Audio probe: speaker={self.tts.speaker_available} ({self.tts.engine}), "
                f"mic={self.stt.mic_available} ({self.stt.engine})",
            )
        return self.get_status()

    async def speak(self, text: str, rate: int = 165, play_on_speaker: bool = True) -> Dict[str, Any]:
        res = await self.tts.speak(text, rate=rate, play_on_speaker=play_on_speaker)
        self._record_history("tts", text, {"played_on_speaker": res["played_on_speaker"]})
        return res

    async def synthesize_wav(self, text: str, rate: int = 165) -> Optional[bytes]:
        return await self.tts.synthesize_wav(text, rate=rate)

    async def process_command_text(
        self,
        text: str,
        execute: bool = True,
        speak_reply: bool = True,
    ) -> Dict[str, Any]:
        self._record_history("stt", text)
        if execute:
            cmd_res = await execute_voice_command(self.controller, text)
        else:
            cmd_res = {"recognized": True, "intent": None, "executed": False, "reply": text}

        tts_res = None
        if speak_reply and cmd_res.get("reply"):
            tts_res = await self.speak(cmd_res["reply"], play_on_speaker=True)

        return {
            "transcript": text,
            **cmd_res,
            "tts": tts_res,
        }

    async def process_audio_wav(
        self,
        wav_bytes: bytes,
        execute: bool = True,
        speak_reply: bool = True,
    ) -> Dict[str, Any]:
        stt_res = await self.stt.transcribe_wav(wav_bytes)
        if not stt_res.get("ok") or not stt_res.get("text"):
            return {
                "ok": False,
                "transcript": "",
                "stt": stt_res,
                "recognized": False,
                "executed": False,
                "reply": stt_res.get("error") or "No speech recognized.",
            }

        cmd_res = await self.process_command_text(
            stt_res["text"],
            execute=execute,
            speak_reply=speak_reply,
        )
        return {
            "ok": True,
            "stt": stt_res,
            **cmd_res,
        }
