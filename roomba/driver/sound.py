"""
Sound, Melody, RTTTL Ringtone, and Morse Code audio synthesis for Roomba 960.
Converts musical melodies into Roomba Open Interface song packets (Opcode 140/141).
"""

from __future__ import annotations

import io
import logging
import os
import re
import tempfile
from typing import List, Tuple, Dict, Any, Optional, Union

try:
    import numpy as np
    import scipy.signal as signal
    from scipy.io import wavfile
    _HAS_DSP = True
except ImportError:
    _HAS_DSP = False
    np = None  # type: ignore
    signal = None  # type: ignore
    wavfile = None  # type: ignore

logger = logging.getLogger(__name__)

# Optional Windows SAPI support
try:
    import pythoncom
    import win32com.client
    _HAS_SAPI = True
except ImportError:
    _HAS_SAPI = False

# MIDI base note mapping
NOTE_TO_SEMITONE = {
    "c": 0, "c#": 1, "db": 1,
    "d": 2, "d#": 3, "eb": 3,
    "e": 4,
    "f": 5, "f#": 6, "gb": 6,
    "g": 7, "g#": 8, "ab": 8,
    "a": 9, "a#": 10, "bb": 10,
    "b": 11, "h": 11,
}

# Morse Code Dictionary
MORSE_MAP = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".",
    "F": "..-.", "G": "--.", "H": "....", "I": "..", "J": ".---",
    "K": "-.-", "L": ".-..", "M": "--", "N": "-.", "O": "---",
    "P": ".--.", "Q": "--.-", "R": ".-.", "S": "...", "T": "-",
    "U": "..-", "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--",
    "Z": "--..", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
    "0": "-----", " ": "/",
}

# Human Vocal Gestures & Formant Synthesis Library
HUMAN_SOUNDS: Dict[str, List[Tuple[int, int]]] = {
    # Spoken Words
    # "Hello!": Two-syllable greeting inflection (rising diphthong)
    "hello": [
        (65, 5), (67, 5), (0, 2), (72, 8), (76, 12)
    ],
    # "Yes! / Affirmative": Cheerful rising double-chirp
    "yes": [
        (67, 6), (0, 2), (74, 10)
    ],
    # "No-No / Refusal": Two sharp assertive descending vocal pulses
    "no": [
        (72, 7), (0, 3), (67, 9)
    ],
    # "Roomba": Formant synthesis of "Room-ba" name
    "roomba": [
        (62, 6), (60, 8), (0, 2), (55, 4), (69, 10), (72, 12)
    ],
    # "Help": Urgent rising inflection
    "help": [
        (74, 4), (76, 8), (80, 6), (88, 3)
    ],
    # "Danger": Two-tone urgent warning
    "danger": [
        (76, 6), (74, 4), (67, 6), (0, 2), (71, 8), (69, 10)
    ],
    # "Stop": Crisp assertive halt command
    "stop": [
        (96, 2), (90, 2), (64, 8), (67, 8), (88, 3)
    ],
    # "Thank You": Warm two-syllable cadence
    "thank_you": [
        (90, 3), (69, 6), (72, 6), (0, 2), (77, 8), (60, 10)
    ],
    # "Goodbye": Melodic descending two-syllable sign-off
    "goodbye": [
        (72, 8), (0, 2), (67, 12), (0, 4), (64, 16)
    ],

    # Emotional Vocal Gestures
    # "Uh-oh!": Classic two-note human warning / mistake vocalization (descending minor third)
    "uh_oh": [
        (72, 8), (0, 4), (67, 14)
    ],
    # "Laugh / Ha-Ha-Ha": Human laughter burst with natural pitch and volume cadence
    "laugh": [
        (74, 5), (0, 3), (74, 5), (0, 3), (72, 5), (0, 3), (71, 6), (0, 3), (69, 10)
    ],
    # "Scream": Piercing high-frequency human vocal alarm
    "scream": [
        (65, 3), (72, 4), (77, 4), (84, 5), (89, 6), (93, 8), (96, 12), (93, 8), (89, 6)
    ],
    # "Wow!": Gliding human vocal expression of wonder (inflected scoop)
    "wow": [
        (60, 4), (64, 4), (69, 6), (74, 8), (72, 10), (67, 8)
    ],
    # "Sigh": Soft descending human exhale
    "sigh": [
        (76, 6), (74, 6), (72, 8), (69, 10), (65, 12), (60, 16)
    ],
    # "Cough": Dry human throat-clearing plosive cough burst
    "cough": [
        (80, 2), (62, 4), (0, 4), (82, 2), (60, 6)
    ],
    # "Gasp": Sudden sharp intake of breath
    "gasp": [
        (60, 4), (67, 5), (76, 6), (84, 8)
    ],
    # "Yawn": Long rising vocal stretch into relaxed release
    "yawn": [
        (55, 10), (60, 10), (65, 12), (70, 14), (67, 12), (62, 16), (57, 20)
    ],
    # "Sneeze / Achoo": Sharp rising inhalation followed by explosive sneeze drop
    "sneeze": [
        (65, 4), (70, 5), (77, 6), (0, 3), (84, 4), (60, 14)
    ],
    # "Whistle": Human melodic whistle call
    "whistle": [
        (84, 8), (88, 8), (91, 12), (0, 4), (88, 8), (91, 16)
    ],
    # "Giggle": High-pitched playful human chuckle
    "giggle": [
        (79, 4), (0, 2), (81, 4), (0, 2), (79, 4), (0, 2), (83, 6), (0, 2), (81, 8)
    ],
    # "Groan": Low strained human vocalization
    "groan": [
        (50, 12), (48, 14), (46, 16), (45, 20)
    ],
    # "Hmm / Pondering": Thoughtful rising-falling vocalization
    "hmm": [
        (60, 12), (62, 14), (60, 16)
    ],
}

# Standard Preset Tunes: (MIDI note, duration in 1/64s)
PRESET_TUNES: Dict[str, List[Tuple[int, int]]] = {
    "mario": [
        (76, 8), (76, 8), (0, 8), (76, 8), (0, 8), (72, 8), (76, 8), (0, 8),
        (79, 16), (0, 16), (67, 16), (0, 16),
    ],
    "imperial": [
        (67, 32), (67, 32), (67, 32), (63, 24), (70, 8), (67, 32), (63, 24),
        (70, 8), (67, 48),
    ],
    "charge": [
        (60, 8), (64, 8), (67, 8), (72, 16), (67, 8), (72, 24),
    ],
    "zelda": [
        (71, 8), (70, 8), (68, 8), (65, 8), (66, 8), (73, 8), (78, 16),
    ],
    "alert": [
        (84, 8), (72, 8), (84, 8), (72, 8), (84, 8), (72, 8), (84, 12)
    ],
    "happy": [
        (60, 8), (64, 8), (67, 8), (72, 8), (76, 8), (79, 16)
    ],
    "sad": [
        (72, 16), (71, 16), (70, 16), (69, 24)
    ],
    "nokia": [
        (88, 8), (86, 8), (78, 16), (80, 16),
        (84, 8), (83, 8), (74, 16), (76, 16),
        (81, 8), (79, 8), (71, 16), (73, 16), (76, 24)
    ],
    "r2d2": [
        (84, 6), (96, 6), (91, 6), (103, 6), (88, 6), (93, 12)
    ],
    # Include human sounds in presets
    **HUMAN_SOUNDS,
}

RTTTL_SAMPLES = {
    "mario": "mario:d=4,o=5,b=100:16e6,16e6,32p,8e6,16c6,8e6,8g6,8p,8g",
    "starwars": "starwars:d=4,o=5,b=112:8d,8d,8d,2g,2d6,8c6,8b,8a,2g6,d6",
    "mission": "mission:d=4,o=6,b=150:16d5,16f5,16g5,16d5,16f5,16g5",
}


def rtttl_to_notes(rtttl_str: str) -> List[Tuple[int, int]]:
    """
    Parse an RTTTL ringtone string into Roomba notes (MIDI pitch, duration in 1/64s).
    Format: name:d=4,o=5,b=120:note,note,...
    """
    parts = rtttl_str.strip().split(":")
    if len(parts) < 3:
        raise ValueError("Invalid RTTTL format. Expected 'name:defaults:notes'")

    # Defaults
    defaults = parts[1].split(",")
    default_duration = 4
    default_octave = 5
    bpm = 120

    for d in defaults:
        kv = d.strip().split("=")
        if len(kv) == 2:
            key, val = kv[0].strip().lower(), kv[1].strip()
            if key == "d":
                default_duration = int(val)
            elif key == "o":
                default_octave = int(val)
            elif key == "b":
                bpm = int(val)

    # 1 whole note in seconds = 4 * 60 / bpm
    whole_note_sec = (4.0 * 60.0) / bpm

    note_pattern = re.compile(r"^(\d+)?([a-g,p]#?b?)(\.)?(\d+)?$", re.IGNORECASE)
    notes_str = parts[2].split(",")
    result: List[Tuple[int, int]] = []

    for item in notes_str:
        item = item.strip()
        if not item:
            continue
        m = note_pattern.match(item)
        if not m:
            continue

        dur_str, note_name, dot, oct_str = m.groups()
        dur_val = int(dur_str) if dur_str else default_duration
        oct_val = int(oct_str) if oct_str else default_octave
        note_name = note_name.lower()

        # Calculate duration in seconds and convert to 1/64s
        sec = whole_note_sec / dur_val
        if dot:
            sec *= 1.5
        dur_64th = max(1, min(255, int(round(sec * 64.0))))

        if note_name == "p":
            pitch = 0  # Pause / silence
        else:
            semitone = NOTE_TO_SEMITONE.get(note_name, 0)
            # Octave 4 C is MIDI 60: pitch = (octave + 1) * 12 + semitone
            pitch = (oct_val + 1) * 12 + semitone
            pitch = max(31, min(127, pitch))

        result.append((pitch, dur_64th))

    return result


def text_to_morse_notes(
    text: str,
    note: int = 76,
    dot_duration: int = 6,
    base_note: Optional[int] = None,
    unit_duration_64th: Optional[int] = None,
) -> List[Tuple[int, int]]:
    """
    Convert text string into Morse code audio beeps.
    Dot = 1 unit, Dash = 3 units, intra-char gap = 1 unit, char gap = 3 units, word gap = 7 units.
    """
    if base_note is not None:
        note = base_note
    if unit_duration_64th is not None:
        dot_duration = unit_duration_64th

    result: List[Tuple[int, int]] = []
    clean_text = text.upper()

    pitch = max(31, min(127, int(note if note is not None else 76)))
    dot_dur = max(1, min(64, int(dot_duration if dot_duration is not None else 6)))
    dash_dur = dot_dur * 3
    elem_gap = dot_dur
    char_gap = dot_dur * 3
    word_gap = dot_dur * 7

    for idx, char in enumerate(clean_text):
        if char == " ":
            result.append((0, word_gap))
            continue

        pattern = MORSE_MAP.get(char)
        if not pattern:
            continue

        for p_idx, symbol in enumerate(pattern):
            dur = dash_dur if symbol == "-" else dot_dur
            result.append((pitch, dur))
            # Intra-character gap between elements
            if p_idx < len(pattern) - 1:
                result.append((0, elem_gap))

        # Inter-character gap
        if idx < len(clean_text) - 1 and clean_text[idx + 1] != " ":
            result.append((0, char_gap))

    return result


def text_to_vocal_tones(text: str) -> List[Tuple[int, int]]:
    """
    Synthesize human-like vocal sounds, formant approximations, and prosody
    on the Roomba's internal tone generator for arbitrary text.
    Vowels alternate formant frequencies; consonants produce percussive/humming transitions;
    inflections adapt to sentence punctuation (?, !).
    """
    VOWEL_FORMANTS: Dict[str, List[Tuple[int, int]]] = {
        "a": [(69, 4), (72, 4)],  # [a] "ah"
        "e": [(76, 3), (80, 3)],  # [e] "eh"
        "i": [(81, 3), (84, 3)],  # [i] "ee"
        "o": [(64, 4), (67, 4)],  # [o] "oh"
        "u": [(60, 5), (62, 5)],  # [u] "oo"
    }

    CONSONANTS: Dict[str, Tuple[int, int]] = {
        "b": (55, 2), "p": (88, 2), "t": (90, 2), "d": (62, 2),
        "k": (92, 2), "g": (58, 2), "s": (96, 2), "z": (67, 2),
        "m": (57, 4), "n": (60, 4), "l": (64, 4), "r": (62, 4),
        "h": (74, 3), "w": (58, 3), "y": (77, 3), "v": (58, 2),
        "f": (94, 2), "c": (92, 2), "j": (69, 3), "q": (92, 2),
        "x": (94, 2),
    }

    notes: List[Tuple[int, int]] = []
    clean = text.lower().strip()
    is_question = clean.endswith("?")
    is_exclamation = clean.endswith("!")

    # Strip punctuation for phonetic parsing
    cleaned_words = clean.replace("?", "").replace("!", "").replace(".", "").replace(",", "").split()
    for w_idx, word in enumerate(cleaned_words):
        for char in word:
            if char in VOWEL_FORMANTS:
                for p, d in VOWEL_FORMANTS[char]:
                    if is_question and w_idx == len(cleaned_words) - 1:
                        p += 4  # Rising question intonation
                    elif is_exclamation:
                        p += 2  # Higher energy
                    notes.append((max(31, min(127, p)), d))
            elif char in CONSONANTS:
                p, d = CONSONANTS[char]
                notes.append((p, d))

        if w_idx < len(cleaned_words) - 1:
            notes.append((0, 4))  # Inter-word vocal pause

    return notes


def grind_audio_to_roomba_notes(
    audio_data: np.ndarray,
    sample_rate: int,
    mode: str = "formant_interleave",
    silence_thresh_ratio: float = 0.03,
) -> List[Tuple[int, int]]:
    """
    Grind arbitrary audio signals (human speech, laughter, vocalizations, cries)
    down into Roomba Open Interface Opcode 140 (Song) notes: (midi_pitch, duration_in_64ths).

    Features:
    - 64 Hz time-slicing matching Roomba's native 1/64s timer resolution (~15.625 ms).
    - Voice Activity Detection (VAD) via RMS energy.
    - Zero-Crossing Rate (ZCR) detection for unvoiced consonant / fricative noise transients.
    - Time-Division Formant Multiplexing (alternating F1 & F2 at 64 Hz) for composite vowel perception.
    - Run-length duration compression (up to 250/64s) for smooth transitions and compact packets.
    """
    if not _HAS_DSP:
        raise RuntimeError("numpy and scipy are required for audio analysis. Install with: pip install numpy scipy")

    if audio_data is None or len(audio_data) == 0:
        return []

    # Downmix multi-channel to mono
    if audio_data.ndim > 1:
        audio_data = audio_data.mean(axis=1)

    audio = audio_data.astype(np.float32)
    max_val = np.max(np.abs(audio)) if len(audio) > 0 else 1.0
    if max_val > 0:
        audio = audio / max_val  # Normalize to [-1.0, 1.0]

    # 1/64th second window (~15.625 ms) matching Roomba duration resolution
    frame_len = max(16, int(round(sample_rate / 64.0)))
    hop_len = frame_len

    raw_notes: List[int] = []
    fft_size = max(512, int(2 ** np.ceil(np.log2(frame_len * 2))))

    for i in range(0, len(audio) - frame_len + 1, hop_len):
        frame = audio[i : i + frame_len]
        rms = float(np.sqrt(np.mean(frame**2)))

        # 1. Silence check
        if rms < silence_thresh_ratio:
            raw_notes.append(0)
            continue

        # 2. Zero-crossing rate for unvoiced plosives/fricatives ('s', 'sh', 'f', 't', 'k')
        zcr = float(np.mean(np.abs(np.diff(np.sign(frame))))) / 2.0
        if zcr > 0.22:
            # Unvoiced turbulent noise burst (MIDI 95 to 112)
            f_noise = 2500.0 + (zcr * 2000.0)
            midi_noise = int(round(69 + 12 * np.log2(f_noise / 440.0)))
            raw_notes.append(max(31, min(115, midi_noise)))
            continue

        # 3. Spectral analysis for voiced vocal resonances (formants)
        w_frame = frame * np.hanning(len(frame))
        spec = np.abs(np.fft.rfft(w_frame, n=fft_size))
        freqs = np.fft.rfftfreq(fft_size, d=1.0 / sample_rate)

        # Human vocal formant band: 200 Hz to 3500 Hz
        mask = (freqs >= 200) & (freqs <= 3500)
        v_spec = spec[mask]
        v_freqs = freqs[mask]

        if len(v_spec) == 0 or np.max(v_spec) == 0:
            raw_notes.append(0)
            continue

        if mode == "formant_interleave":
            # Find resonance peaks (Formants F1 & F2)
            peaks, _ = signal.find_peaks(v_spec, height=float(np.max(v_spec)) * 0.22, distance=3)
            if len(peaks) >= 2:
                # Sort peaks by spectral energy descending
                sorted_p = peaks[np.argsort(v_spec[peaks])][::-1]
                f1 = float(v_freqs[sorted_p[0]])
                f2 = float(v_freqs[sorted_p[1]])
                m1 = max(31, min(127, int(round(69 + 12 * np.log2(f1 / 440.0)))))
                m2 = max(31, min(127, int(round(69 + 12 * np.log2(f2 / 440.0)))))
                # Alternate between F1 and F2 on consecutive 1/64s frames (auditory fusion)
                selected_note = m1 if (len(raw_notes) % 2 == 0) else m2
                raw_notes.append(selected_note)
            else:
                best_idx = int(np.argmax(v_spec))
                f = float(v_freqs[best_idx])
                m = max(31, min(127, int(round(69 + 12 * np.log2(f / 440.0)))))
                raw_notes.append(m)

        elif mode == "pitch_f0":
            # Fundamental frequency tracking (80 Hz - 400 Hz)
            f0_mask = (freqs >= 80) & (freqs <= 450)
            f0_spec = spec[f0_mask]
            f0_freqs = freqs[f0_mask]
            if len(f0_spec) > 0 and np.max(f0_spec) > 0:
                best_f0 = float(f0_freqs[np.argmax(f0_spec)])
                m = max(31, min(127, int(round(69 + 12 * np.log2(best_f0 / 440.0)))))
                raw_notes.append(m)
            else:
                raw_notes.append(0)

        else:  # "dominant_peak"
            best_idx = int(np.argmax(v_spec))
            f = float(v_freqs[best_idx])
            m = max(31, min(127, int(round(69 + 12 * np.log2(f / 440.0)))))
            raw_notes.append(m)

    # 4. Compress consecutive identical notes into longer durations
    compressed: List[Tuple[int, int]] = []
    curr_note: Optional[int] = None
    curr_dur = 0

    for n in raw_notes:
        if n == curr_note and curr_dur < 250:
            curr_dur += 1
        else:
            if curr_note is not None:
                compressed.append((curr_note, curr_dur))
            curr_note = n
            curr_dur = 1

    if curr_note is not None:
        compressed.append((curr_note, curr_dur))

    return compressed


def grind_wav_bytes_to_notes(
    wav_bytes: bytes,
    mode: str = "formant_interleave",
    silence_thresh_ratio: float = 0.03,
) -> List[Tuple[int, int]]:
    """
    Parse standard WAV audio bytes and grind down into Roomba Open Interface notes.
    """
    buf = io.BytesIO(wav_bytes)
    sr, data = wavfile.read(buf)
    return grind_audio_to_roomba_notes(
        data,
        sample_rate=sr,
        mode=mode,
        silence_thresh_ratio=silence_thresh_ratio,
    )


def generate_phonetic_waveform(text: str, sample_rate: int = 16000) -> Any:
    """
    Pure Python acoustic vocal tract acoustic synthesizer (fallback when SAPI is unavailable).
    Models glottal pulse train excitation and F1/F2 vocal tract filter resonances.
    """
    if not _HAS_DSP:
        raise RuntimeError("numpy and scipy are required for phonetic waveform synthesis. Install with: pip install numpy scipy")
    VOWEL_PARAMS: Dict[str, Tuple[float, float, float]] = {
        "a": (130.0, 750.0, 1200.0),
        "e": (140.0, 500.0, 1800.0),
        "i": (150.0, 280.0, 2300.0),
        "o": (120.0, 500.0, 900.0),
        "u": (110.0, 320.0, 800.0),
    }

    t_frames: List[np.ndarray] = []
    dt = 1.0 / float(sample_rate)

    clean_words = text.lower().replace("?", "").replace("!", "").replace(".", "").replace(",", "").split()
    for word in clean_words:
        for ch in word:
            f0, f1, f2 = VOWEL_PARAMS.get(ch, (130.0, 600.0, 1400.0))
            dur = 0.12 if ch in VOWEL_PARAMS else 0.05
            n_samples = max(16, int(dur * sample_rate))
            t = np.arange(n_samples, dtype=np.float32) * dt

            # Glottal pulse source + vocal tract formant filter
            glottal = signal.sawtooth(2.0 * np.pi * f0 * t, width=0.1)
            formants = 0.6 * np.sin(2.0 * np.pi * f1 * t) + 0.4 * np.sin(2.0 * np.pi * f2 * t)

            if ch not in VOWEL_PARAMS and ch in "ptkcsxf":
                # Unvoiced consonant transient
                noise = np.random.uniform(-1.0, 1.0, n_samples).astype(np.float32)
                frame = 0.7 * noise + 0.3 * formants
            else:
                frame = glottal * 0.4 + formants * 0.6

            frame *= np.hanning(n_samples)
            t_frames.append(frame)

        # Word gap
        t_frames.append(np.zeros(int(0.08 * sample_rate), dtype=np.float32))

    if not t_frames:
        return np.zeros(int(sample_rate * 0.2), dtype=np.float32)

    return np.concatenate(t_frames).astype(np.float32)


def synthesize_and_grind_speech(
    text: str,
    rate: int = 0,
    mode: str = "formant_interleave",
) -> List[Tuple[int, int]]:
    """
    Synthesize human speech audio from text using Windows SAPI (or phonetic fallback)
    and grind the resulting acoustic waveform into Roomba Open Interface notes.
    """
    if not text.strip():
        return []

    # 1. Try Windows SAPI Speech Synthesis to WAV
    if _HAS_SAPI:
        try:
            pythoncom.CoInitialize()
            voice = win32com.client.Dispatch("SAPI.SpVoice")
            stream = win32com.client.Dispatch("SAPI.SpFileStream")
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp_path = tmp.name
            tmp.close()
            try:
                stream.Open(tmp_path, 3)  # SSFMCreateForWrite
                voice.AudioOutputStream = stream
                voice.Rate = max(-10, min(10, int(rate)))
                voice.Speak(text)
                stream.Close()
                with open(tmp_path, "rb") as f:
                    wav_data = f.read()
                return grind_wav_bytes_to_notes(wav_data, mode=mode)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
        except Exception as e:
            logger.warning(f"SAPI voice synthesis warning: {e}. Falling back to acoustic model.")

    # 2. Pure Python Fallback Acoustic Model
    audio = generate_phonetic_waveform(text, sample_rate=16000)
    return grind_audio_to_roomba_notes(audio, sample_rate=16000, mode=mode)

