"""
English Text-to-Speech (TTS) Engine Abstraction.
Supports local synthesis via espeak-ng / espeak / pyttsx3 when installed,
plays on Raspberry Pi speakers when connected, and returns WAV bytes
for browser playback when speakers are not yet attached.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger("roomba.voice.tts")


def detect_speaker_hardware() -> tuple[bool, Optional[str]]:
    """
    Probe for audio output (speaker) hardware without raising exceptions.
    Returns (available, error_message).
    """
    if sys.platform == "linux":
        # Check ALSA sound cards
        cards_path = Path("/proc/asound/cards")
        if cards_path.exists():
            try:
                content = cards_path.read_text(errors="ignore").strip()
                if not content or "no soundcards" in content.lower():
                    return False, "No speakers / ALSA audio output device detected."
                # Even if HDMI audio exists on Pi 5, check aplay -l if available
                if shutil.which("aplay"):
                    proc = subprocess.run(
                        ["aplay", "-l"],
                        capture_output=True,
                        text=True,
                        timeout=2.0,
                    )
                    if proc.returncode != 0 or "card " not in proc.stdout.lower():
                        return False, "No speaker playback device found (aplay -l empty)."
                return True, None
            except Exception as e:
                return False, f"Speaker probe failed: {e}"
        return False, "No audio subsystem (/proc/asound) detected."

    # Non-Linux (e.g. Windows dev machine)
    try:
        import importlib.util
        if importlib.util.find_spec("pyttsx3") is not None:
            return True, None
    except Exception:
        pass
    return False, "No local speaker driver configured (browser TTS fallback active)."


def detect_tts_engine() -> str:
    """Detect best available local English TTS backend."""
    if shutil.which("espeak-ng"):
        return "espeak-ng"
    if shutil.which("espeak"):
        return "espeak"
    try:
        import importlib.util
        if importlib.util.find_spec("pyttsx3") is not None:
            return "pyttsx3"
    except Exception:
        pass
    return "browser_fallback"


class TTSEngine:
    """English Text-to-Speech synthesizer and speaker player."""

    def __init__(self):
        self.engine: str = "browser_fallback"
        self.speaker_available: bool = False
        self.speaker_error: Optional[str] = None
        self.probe()

    def probe(self) -> Dict[str, Any]:
        """Re-scan local TTS engines and speaker hardware."""
        self.engine = detect_tts_engine()
        self.speaker_available, self.speaker_error = detect_speaker_hardware()
        return self.get_status()

    def get_status(self) -> Dict[str, Any]:
        return {
            "engine": self.engine,
            "language": "en",
            "speaker_available": self.speaker_available,
            "speaker_error": self.speaker_error,
            "browser_fallback_ready": True,
        }

    def _synthesize_wav_sync(self, text: str, rate: int = 165) -> Optional[bytes]:
        """Synthesize English text into WAV bytes synchronously."""
        clean_text = (text or "").strip()
        if not clean_text:
            return None

        if self.engine in ("espeak-ng", "espeak"):
            exe = shutil.which(self.engine)
            if exe:
                try:
                    proc = subprocess.run(
                        [exe, "--stdout", "-v", "en", "-s", str(rate), "--", clean_text],
                        capture_output=True,
                        timeout=10.0,
                    )
                    if proc.returncode == 0 and proc.stdout:
                        return proc.stdout
                except Exception as e:
                    logger.warning(f"{self.engine} synthesis failed: {e}")

        if self.engine == "pyttsx3":
            try:
                import pyttsx3
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                    tmp_path = tf.name
                try:
                    eng = pyttsx3.init()
                    eng.setProperty("rate", rate)
                    eng.save_to_file(clean_text, tmp_path)
                    eng.runAndWait()
                    data = Path(tmp_path).read_bytes()
                    return data if data else None
                finally:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
            except Exception as e:
                logger.warning(f"pyttsx3 synthesis failed: {e}")

        return None

    async def synthesize_wav(self, text: str, rate: int = 165) -> Optional[bytes]:
        """Async wrapper for WAV synthesis."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._synthesize_wav_sync, text, rate)

    def _play_wav_sync(self, wav_bytes: bytes) -> bool:
        """Play WAV bytes on local speakers if available."""
        if not self.speaker_available or not wav_bytes:
            return False
        if sys.platform == "linux" and shutil.which("aplay"):
            try:
                proc = subprocess.run(
                    ["aplay", "-q", "-"],
                    input=wav_bytes,
                    capture_output=True,
                    timeout=15.0,
                )
                return proc.returncode == 0
            except Exception as e:
                logger.warning(f"aplay playback error: {e}")
                return False
        return False

    async def speak(self, text: str, rate: int = 165, play_on_speaker: bool = True) -> Dict[str, Any]:
        """
        Synthesize English speech. Plays on local speakers if connected,
        and indicates whether browser fallback should be used.
        """
        wav_bytes = await self.synthesize_wav(text, rate=rate)
        played_locally = False
        if play_on_speaker and self.speaker_available:
            if wav_bytes is not None:
                loop = asyncio.get_running_loop()
                played_locally = await loop.run_in_executor(None, self._play_wav_sync, wav_bytes)
            elif self.engine == "pyttsx3":
                try:
                    import pyttsx3
                    def _say():
                        eng = pyttsx3.init()
                        eng.setProperty("rate", rate)
                        eng.say(text)
                        eng.runAndWait()
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, _say)
                    played_locally = True
                except Exception as e:
                    logger.warning(f"pyttsx3 say failed: {e}")

        return {
            "text": text,
            "engine": self.engine,
            "has_wav": wav_bytes is not None,
            "played_on_speaker": played_locally,
            "browser_fallback": not played_locally,
        }
