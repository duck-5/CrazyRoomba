"""
Sound, Melody, RTTTL Ringtone, and Morse Code audio synthesis for Roomba 960.
Converts musical melodies into Roomba Open Interface song packets (Opcode 140/141).
"""

from __future__ import annotations

import re
from typing import List, Tuple, Dict, Any, Optional

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
    # "Hello!": Two-syllable greeting inflection (rising diphthong)
    "hello": [
        (65, 5), (67, 5), (0, 2), (72, 8), (76, 12)
    ],
    # "Uh-oh!": Classic two-note human warning / mistake vocalization (descending minor third)
    "uh_oh": [
        (72, 8), (0, 4), (67, 14)
    ],
    # "Laugh / Ha-Ha-Ha": Human laughter burst with natural pitch and volume cadence
    "laugh": [
        (74, 5), (0, 3), (74, 5), (0, 3), (72, 5), (0, 3), (71, 6), (0, 3), (69, 10)
    ],
    # "Wow!": Gliding human vocal expression of wonder (inflected scoop)
    "wow": [
        (60, 4), (64, 4), (69, 6), (74, 8), (72, 10), (67, 8)
    ],
    # "Yes! / Affirmative": Cheerful rising double-chirp
    "yes": [
        (67, 6), (0, 2), (74, 10)
    ],
    # "No-No / Refusal": Two sharp assertive descending vocal pulses
    "no": [
        (72, 7), (0, 3), (67, 9)
    ],
    # "Sigh": Soft descending human exhale
    "sigh": [
        (76, 6), (74, 6), (72, 8), (69, 10), (65, 12), (60, 16)
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
    # "Hmm / Pondering": Thoughtful rising-falling vocalization
    "hmm": [
        (60, 12), (62, 14), (60, 16)
    ],
    # "Goodbye": Melodic descending two-syllable sign-off
    "goodbye": [
        (72, 8), (0, 2), (67, 12), (0, 4), (64, 16)
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
