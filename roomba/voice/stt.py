"""
English Speech-to-Text (STT) Engine Abstraction.
Probes for Raspberry Pi microphone hardware without crashing when absent,
supports offline WAV transcription when vosk/speech_recognition is installed,
and pairs with browser Web Speech API when no Pi microphone is connected yet.
"""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import logging
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger("roomba.voice.stt")


def detect_microphone_hardware() -> tuple[bool, Optional[str]]:
    """
    Probe for audio input (microphone) hardware without raising exceptions.
    Returns (available, error_message).
    """
    if sys.platform == "linux":
        cards_path = Path("/proc/asound/cards")
        if not cards_path.exists():
            return False, "No audio subsystem (/proc/asound) detected."
        if shutil.which("arecord"):
            try:
                proc = subprocess.run(
                    ["arecord", "-l"],
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                )
                if proc.returncode != 0 or "card " not in proc.stdout.lower():
                    return False, "No microphone detected (arecord -l found no capture devices)."
                return True, None
            except Exception as e:
                return False, f"Microphone probe failed: {e}"
        return False, "No microphone detected (arecord utility unavailable)."

    # Non-Linux fallback probe
    try:
        if importlib.util.find_spec("speech_recognition") is not None:
            return True, None
    except Exception:
        pass
    return False, "No local microphone configured (use Browser Mic STT or text command)."


def detect_stt_engine() -> str:
    """Detect best available local English STT backend."""
    if importlib.util.find_spec("vosk") is not None:
        model_dir = os.getenv("ROOMBA_VOSK_MODEL", "/app/models/vosk-model-small-en-us-0.15")
        if Path(model_dir).exists():
            return "vosk"
    if importlib.util.find_spec("speech_recognition") is not None:
        return "speech_recognition"
    return "browser_web_speech"


class STTEngine:
    """English Speech-to-Text engine with graceful no-mic fallback."""

    def __init__(self):
        self.engine: str = "browser_web_speech"
        self.mic_available: bool = False
        self.mic_error: Optional[str] = None
        self.probe()

    def probe(self) -> Dict[str, Any]:
        """Re-scan local STT engines and microphone hardware."""
        self.engine = detect_stt_engine()
        self.mic_available, self.mic_error = detect_microphone_hardware()
        return self.get_status()

    def get_status(self) -> Dict[str, Any]:
        return {
            "engine": self.engine,
            "language": "en-US",
            "mic_available": self.mic_available,
            "mic_error": self.mic_error,
            "browser_fallback_ready": True,
        }

    def _transcribe_wav_sync(self, wav_bytes: bytes) -> Dict[str, Any]:
        """Synchronously transcribe WAV audio bytes to English text."""
        if not wav_bytes:
            return {"ok": False, "text": "", "engine": self.engine, "error": "Empty audio payload."}

        if self.engine == "vosk":
            try:
                import vosk
                model_dir = os.getenv("ROOMBA_VOSK_MODEL", "/app/models/vosk-model-small-en-us-0.15")
                model = vosk.Model(model_dir)
                with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                    rec = vosk.KaldiRecognizer(model, wf.getframerate())
                    while True:
                        data = wf.readframes(4000)
                        if len(data) == 0:
                            break
                        rec.AcceptWaveform(data)
                    res = json.loads(rec.FinalResult())
                    text = res.get("text", "").strip()
                    return {"ok": True, "text": text, "engine": "vosk", "error": None}
            except Exception as e:
                return {"ok": False, "text": "", "engine": "vosk", "error": f"Vosk transcription failed: {e}"}

        if self.engine == "speech_recognition":
            try:
                import speech_recognition as sr
                recognizer = sr.Recognizer()
                with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
                    audio = recognizer.record(source)
                # Prefer offline sphinx if installed, else Google Web Speech
                if importlib.util.find_spec("pocketsphinx") is not None:
                    text = recognizer.recognize_sphinx(audio, language="en-US")
                else:
                    text = recognizer.recognize_google(audio, language="en-US")
                return {"ok": True, "text": text.strip(), "engine": "speech_recognition", "error": None}
            except Exception as e:
                return {"ok": False, "text": "", "engine": "speech_recognition", "error": f"STT failed: {e}"}

        return {
            "ok": False,
            "text": "",
            "engine": self.engine,
            "error": "No server-side STT model (vosk/SpeechRecognition) installed. Use Browser Mic STT or text command.",
        }

    async def transcribe_wav(self, wav_bytes: bytes) -> Dict[str, Any]:
        """Async wrapper to transcribe WAV bytes without blocking the event loop."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._transcribe_wav_sync, wav_bytes)
