"""
8-Bit Chiptune Songs, Robot Sound Marks, RTTTL Ringtones, and Morse Code for Roomba 960.
Converts melodies into Roomba Open Interface song packets (Opcode 140/141).
Pure Python with zero external DSP / speech dependencies.
"""

from __future__ import annotations

import logging
import re
from typing import List, Tuple, Dict, Optional, Sequence

logger = logging.getLogger(__name__)

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

# ---------------------------------------------------------------------------
# 8-Bit Chiptune Video Game Songs (MIDI note, duration in 1/64s)
# ---------------------------------------------------------------------------
EIGHT_BIT_SONGS: Dict[str, List[Tuple[int, int]]] = {
    # Tetris: Korobeiniki (A-Theme)
    "tetris": [
        (76, 12), (71, 6), (72, 6), (74, 12), (72, 6), (71, 6),
        (69, 12), (69, 6), (72, 6), (76, 12), (74, 6), (72, 6),
        (71, 18), (72, 6), (74, 12), (76, 12),
        (72, 12), (69, 12), (69, 12), (0, 12),
        (74, 16), (77, 8), (81, 12), (79, 6), (77, 6),
        (76, 18), (72, 6), (76, 12), (74, 6), (72, 6),
        (71, 12), (71, 6), (72, 6), (74, 12), (76, 12),
        (72, 12), (69, 12), (69, 16),
    ],

    # Mario Kart: Race Start Countdown (3 beeps + GO)
    "mario_kart_start": [
        (77, 10), (0, 22),
        (77, 10), (0, 22),
        (77, 10), (0, 22),
        (82, 40),
    ],

    # Mario Kart: Mario Circuit SNES Main Theme
    "mario_kart_circuit": [
        (72, 6), (76, 6), (79, 6), (84, 10), (0, 4),
        (83, 6), (79, 6), (81, 10), (0, 4),
        (77, 6), (81, 6), (84, 6), (88, 10), (0, 4),
        (86, 6), (83, 6), (84, 16), (0, 8),
        (79, 6), (79, 4), (0, 2), (79, 6), (76, 6), (72, 8),
        (74, 6), (76, 6), (77, 6), (79, 12), (72, 16),
    ],

    # Super Mario Bros: Overworld Theme
    "mario_overworld": [
        (76, 6), (76, 6), (0, 6), (76, 6), (0, 6), (72, 6), (76, 12),
        (79, 12), (0, 12), (67, 12), (0, 12),
        (72, 9), (0, 3), (67, 9), (0, 3), (64, 9), (0, 3),
        (69, 8), (71, 8), (70, 6), (69, 8),
        (67, 6), (76, 8), (79, 8), (81, 10), (77, 6), (79, 6),
        (0, 4), (76, 8), (72, 6), (74, 6), (71, 12),
    ],

    # Super Mario Bros: Invincibility Starman
    "mario_starman": [
        (72, 4), (72, 4), (72, 4), (0, 4), (72, 4), (72, 4), (72, 4), (0, 4),
        (71, 4), (71, 4), (71, 4), (0, 4), (71, 4), (71, 4), (71, 4), (0, 4),
        (70, 4), (70, 4), (70, 4), (0, 4), (70, 4), (70, 4), (70, 4), (0, 4),
        (69, 4), (69, 4), (69, 4), (0, 4), (68, 4), (67, 4), (66, 4), (65, 8),
    ],

    # Super Mario Bros: Underground Theme
    "mario_underground": [
        (48, 6), (60, 6), (45, 6), (57, 6), (46, 6), (58, 12), (0, 12),
        (48, 6), (60, 6), (45, 6), (57, 6), (46, 6), (58, 12), (0, 12),
        (41, 6), (53, 6), (38, 6), (50, 6), (39, 6), (51, 12), (0, 12),
    ],

    # Pac-Man: Intro Theme
    "pacman": [
        (71, 6), (83, 6), (78, 6), (75, 6), (83, 6), (78, 6), (75, 10), (0, 2),
        (72, 6), (84, 6), (79, 6), (76, 6), (84, 6), (79, 6), (76, 10), (0, 2),
        (71, 6), (83, 6), (78, 6), (75, 6), (83, 6), (78, 6), (75, 10), (0, 2),
        (75, 4), (76, 4), (77, 4), (78, 4), (79, 4), (80, 4), (81, 4), (83, 8),
    ],

    # The Legend of Zelda: Main Fanfare
    "zelda_theme": [
        (70, 24), (0, 8), (65, 12), (70, 8), (72, 4), (74, 4), (75, 4), (77, 24),
        (0, 8), (77, 8), (77, 8), (78, 6), (80, 6), (82, 28),
        (80, 8), (78, 8), (80, 8), (78, 4), (77, 20),
    ],

    # The Legend of Zelda: Secret / Puzzle Solved Chime
    "zelda_secret": [
        (67, 5), (66, 5), (63, 5), (57, 5), (56, 5), (64, 5), (68, 5), (72, 14),
    ],

    # Doom: At Doom's Gate (E1M1 Riff)
    "doom_e1m1": [
        (52, 4), (52, 4), (64, 4), (52, 4), (52, 4), (62, 4), (52, 4), (52, 4),
        (60, 4), (52, 4), (52, 4), (58, 4), (52, 4), (52, 4), (59, 4), (60, 4),
        (52, 4), (52, 4), (64, 4), (52, 4), (52, 4), (62, 4), (52, 4), (52, 4),
        (60, 4), (52, 4), (52, 4), (58, 8), (0, 4),
    ],

    # Pokemon: Red/Blue Opening Theme
    "pokemon_title": [
        (67, 6), (72, 12), (67, 6), (72, 6), (74, 6), (76, 12), (74, 6), (72, 6),
        (74, 18), (67, 6), (67, 6), (69, 6), (71, 6),
        (72, 12), (67, 6), (72, 6), (74, 6), (76, 12), (77, 6), (79, 6),
        (76, 12), (74, 12), (72, 20),
    ],

    # Star Wars: Imperial March
    "imperial_march": [
        (67, 24), (67, 24), (67, 24), (63, 18), (70, 6),
        (67, 24), (63, 18), (70, 6), (67, 36),
        (74, 24), (74, 24), (74, 24), (75, 18), (70, 6),
        (66, 24), (63, 18), (70, 6), (67, 36),
    ],

    # Star Wars: Mos Eisley Cantina Band
    "cantina_band": [
        (69, 6), (74, 6), (69, 6), (74, 6), (69, 6), (74, 6), (69, 6), (68, 6), (69, 6),
        (67, 6), (67, 4), (0, 2), (67, 6), (66, 6), (67, 6), (65, 8), (62, 16),
        (69, 6), (74, 6), (69, 6), (74, 6), (69, 6), (74, 6), (69, 6), (68, 6), (69, 6),
        (67, 12), (0, 4), (65, 12), (0, 4), (62, 18),
    ],

    # Astronomia: Coffin Dance Chiptune
    "coffin_dance": [
        (67, 6), (67, 6), (67, 6), (67, 6), (70, 6), (69, 6), (67, 6), (62, 6),
        (65, 12), (0, 4), (67, 6), (67, 6), (67, 6), (70, 6), (69, 6), (67, 6),
        (74, 12), (0, 4), (72, 12), (0, 4), (70, 6), (69, 6), (67, 12),
    ],

    # Rick Astley: Never Gonna Give You Up
    "rickroll": [
        (65, 6), (67, 6), (70, 6), (67, 6), (74, 14), (74, 14), (72, 20), (0, 6),
        (65, 6), (67, 6), (70, 6), (67, 6), (72, 14), (72, 14), (70, 10), (69, 6), (67, 12),
        (65, 6), (67, 6), (70, 6), (67, 6), (70, 14), (72, 8), (69, 8), (67, 8), (65, 8), (65, 12), (72, 12), (70, 24),
    ],

    # Mega Man 2: Dr. Wily Stage 1
    "megaman": [
        (62, 4), (65, 4), (67, 4), (68, 6), (67, 4), (65, 4), (62, 8), (0, 4),
        (62, 4), (65, 4), (67, 4), (68, 6), (70, 4), (68, 4), (67, 8), (0, 4),
        (72, 6), (70, 6), (68, 6), (67, 6), (65, 6), (63, 6), (62, 16),
    ],
}

# ---------------------------------------------------------------------------
# Robot Sound Marks (Functional Acoustic Cues / Earcons)
# ---------------------------------------------------------------------------
SOUND_MARKS: Dict[str, List[Tuple[int, int]]] = {
    # Ascending boot chime
    "startup": [
        (60, 6), (64, 6), (67, 6), (72, 12),
    ],

    # Descending power-off chime
    "shutdown": [
        (72, 6), (67, 6), (64, 6), (60, 16),
    ],

    # Pleasant affirmative two-tone dock cue
    "dock_success": [
        (67, 8), (72, 16),
    ],

    # Triumphant victory fanfare
    "clean_done": [
        (60, 6), (64, 6), (67, 6), (72, 8), (0, 2), (72, 14),
    ],

    # Double warning boop
    "obstacle_alert": [
        (78, 6), (0, 4), (78, 8),
    ],

    # Rapid high-frequency alarm pulse
    "cliff_warning": [
        (82, 4), (88, 4), (82, 4), (88, 4), (82, 4), (88, 6),
    ],

    # Sad low energy droop
    "low_battery": [
        (64, 10), (62, 10), (60, 16),
    ],

    # Quick affirmative double-chirp
    "ack": [
        (71, 4), (76, 8),
    ],

    # Low blunt error buzzer
    "nack": [
        (51, 6), (0, 2), (48, 10),
    ],

    # Industrial truck style backing up beep
    "reverse_beep": [
        (81, 10), (0, 10), (81, 10), (0, 10),
    ],

    # Cheerful ascending trill
    "happy": [
        (65, 4), (69, 4), (72, 4), (76, 6), (81, 10),
    ],

    # Melancholy sliding droop
    "sad": [
        (72, 10), (71, 10), (68, 12), (65, 18),
    ],
}

# Standard Preset Tunes (combines songs and sound marks, plus classic aliases)
PRESET_TUNES: Dict[str, List[Tuple[int, int]]] = {
    **EIGHT_BIT_SONGS,
    **SOUND_MARKS,
    # Legacy aliases
    "mario": EIGHT_BIT_SONGS["mario_overworld"],
    "imperial": EIGHT_BIT_SONGS["imperial_march"],
    "zelda": EIGHT_BIT_SONGS["zelda_theme"],
    "charge": [(60, 8), (64, 8), (67, 8), (72, 16), (67, 8), (72, 24)],
    "alert": [(84, 8), (72, 8), (84, 8), (72, 8), (84, 8), (72, 8), (84, 12)],
    "nokia": [
        (88, 8), (86, 8), (78, 16), (80, 16),
        (84, 8), (83, 8), (74, 16), (76, 16),
        (81, 8), (79, 8), (71, 16), (73, 16), (76, 24),
    ],
    "r2d2": [(84, 6), (96, 6), (91, 6), (103, 6), (88, 6), (93, 12)],
}

RTTTL_SAMPLES = {
    "tetris": "tetris:d=4,o=5,b=160:e6,8b,8c6,8d6,16e6,16d6,8c6,8b,a,8a,8c6,e6,8d6,8c6,b,8b,8c6,d6,e6,c6,a,2a",
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


def generate_sos_notes(note: int = 76, dot_duration: int = 6) -> List[Tuple[int, int]]:
    """Generate SOS morse code notes."""
    return text_to_morse_notes("SOS", note=note, dot_duration=dot_duration)
