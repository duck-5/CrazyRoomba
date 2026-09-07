"""
Roomba Open Interface (OI) v2 Protocol Definitions.
Opcodes, sensor packet IDs, lookup tables, and Packet 100 binary parsing.
"""

from __future__ import annotations

import re
import struct
import time
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional, List, Tuple, Sequence


class RoombaOpcode:
    """Roomba Open Interface Opcodes."""
    START = 128
    BAUD = 129
    CONTROL = 130
    SAFE = 131
    FULL = 132
    POWER = 133
    SPOT = 134
    CLEAN = 135
    MAX = 136
    DRIVE = 137
    MOTORS = 138
    LEDS = 139
    SONG = 140
    PLAY = 141
    SENSORS = 142
    SEEK_DOCK = 143
    DRIVE_DIRECT = 145
    DRIVE_PWM = 146
    STREAM = 148
    QUERY_LIST = 149
    PAUSE_RESUME_STREAM = 150
    STOP = 173


class RoombaSensorPacket:
    """Sensor Packet IDs and expected byte lengths."""
    ALL_SENSORS_100 = (100, 80)
    ALL_SENSORS_6 = (6, 52)
    BUMPS_WHEEL_DROPS = (7, 1)
    WALL = (8, 1)
    CLIFF_LEFT = (9, 1)
    CLIFF_FRONT_LEFT = (10, 1)
    CLIFF_FRONT_RIGHT = (11, 1)
    CLIFF_RIGHT = (12, 1)
    VIRTUAL_WALL = (13, 1)
    WHEEL_OVERCURRENTS = (14, 1)
    DIRT_DETECT = (15, 1)
    IR_CHAR_OMNI = (17, 1)
    BUTTONS = (18, 1)
    DISTANCE = (19, 2)
    ANGLE = (20, 2)
    CHARGING_STATE = (21, 1)
    VOLTAGE = (22, 2)
    CURRENT = (23, 2)
    TEMPERATURE = (24, 1)
    BATTERY_CHARGE = (25, 2)
    BATTERY_CAPACITY = (26, 2)
    WALL_SIGNAL = (27, 2)
    CLIFF_LEFT_SIGNAL = (28, 2)
    CLIFF_FRONT_LEFT_SIGNAL = (29, 2)
    CLIFF_FRONT_RIGHT_SIGNAL = (30, 2)
    CLIFF_RIGHT_SIGNAL = (31, 2)
    CHARGING_SOURCES_AVAILABLE = (34, 1)
    OI_MODE = (35, 1)
    LEFT_ENCODER = (43, 2)
    RIGHT_ENCODER = (44, 2)
    LIGHT_BUMPER = (45, 1)
    LIGHT_BUMPER_LEFT_SIGNAL = (46, 2)
    LIGHT_BUMPER_FRONT_LEFT_SIGNAL = (47, 2)
    LIGHT_BUMPER_CENTER_LEFT_SIGNAL = (48, 2)
    LIGHT_BUMPER_CENTER_RIGHT_SIGNAL = (49, 2)
    LIGHT_BUMPER_FRONT_RIGHT_SIGNAL = (50, 2)
    LIGHT_BUMPER_RIGHT_SIGNAL = (51, 2)
    LEFT_MOTOR_CURRENT = (52, 2)
    RIGHT_MOTOR_CURRENT = (53, 2)
    MAIN_BRUSH_CURRENT = (54, 2)
    SIDE_BRUSH_CURRENT = (55, 2)
    STASIS = (56, 1)


CHARGING_STATES = {
    0: "Not Charging",
    1: "Reconditioning Charging",
    2: "Full Charging",
    3: "Trickle Charging",
    4: "Waiting",
    5: "Charging Fault",
}

OI_MODES = {
    0: "Off",
    1: "Passive",
    2: "Safe",
    3: "Full",
}

# Struct format string for unpacking 80 bytes of Packet 100
PACKET_100_STRUCT_FMT = ">BBBBBBBBBB BBhh BhhBhH HHHHHBHB BBBBhhhh HHBHHHHHHhhhhBBB"


@dataclass
class RoombaSensors:
    """Complete sensor snapshot parsed from Roomba Open Interface Packet 100 (80 bytes)."""
    timestamp: float

    # --- 1. Bumpers & Wheel Drops ---
    bump_right: bool
    bump_left: bool
    wheel_drop_right: bool
    wheel_drop_left: bool

    # --- 2. Wall & Virtual Wall ---
    wall: bool
    wall_signal: int
    virtual_wall: bool

    # --- 3. Cliff Sensors ---
    cliff_left: bool
    cliff_front_left: bool
    cliff_front_right: bool
    cliff_right: bool
    cliff_left_signal: int
    cliff_front_left_signal: int
    cliff_front_right_signal: int
    cliff_right_signal: int

    # --- 4. Light Bumper (Front Proximity Array) ---
    light_bumper_left: bool
    light_bumper_front_left: bool
    light_bumper_center_left: bool
    light_bumper_center_right: bool
    light_bumper_front_right: bool
    light_bumper_right: bool
    light_bumper_left_signal: int
    light_bumper_front_left_signal: int
    light_bumper_center_left_signal: int
    light_bumper_center_right_signal: int
    light_bumper_front_right_signal: int
    light_bumper_right_signal: int

    # --- 5. Odometry & Encoders ---
    left_encoder: int
    right_encoder: int
    distance_mm: int
    angle_deg: int
    stasis: bool

    # --- 6. Battery & Power ---
    charging_state: str
    charging_state_code: int
    voltage_v: float
    voltage_mv: int
    current_ma: int
    temperature_c: int
    battery_charge_mah: int
    battery_capacity_mah: int
    battery_percent: float
    charging_source_internal: bool
    charging_source_base: bool

    # --- 7. Motor Currents & Overcurrents ---
    left_motor_current_ma: int
    right_motor_current_ma: int
    main_brush_motor_current_ma: int
    side_brush_motor_current_ma: int
    left_wheel_overcurrent: bool
    right_wheel_overcurrent: bool
    main_brush_overcurrent: bool
    side_brush_overcurrent: bool

    # --- 8. User Interface & Misc ---
    dirt_detect: int
    ir_char_omni: int
    button_clean: bool
    button_spot: bool
    button_dock: bool
    button_minute: bool
    button_hour: bool
    button_day: bool
    button_schedule: bool
    button_clock: bool
    oi_mode: str
    oi_mode_code: int

    def to_dict(self) -> Dict[str, Any]:
        """Return sensor data as a dictionary."""
        return asdict(self)

    @classmethod
    def from_bytes(cls, raw: bytes, timestamp: Optional[float] = None) -> "RoombaSensors":
        """Parse raw 80-byte Packet 100 into a RoombaSensors instance."""
        if len(raw) != 80:
            raise ValueError(f"Expected 80 bytes for Packet 100, got {len(raw)}")

        ts = timestamp if timestamp is not None else time.time()
        u = struct.unpack(PACKET_100_STRUCT_FMT, raw)

        b_w = u[0]
        wall_det = bool(u[1])
        cl_l = bool(u[2])
        cl_fl = bool(u[3])
        cl_fr = bool(u[4])
        cl_r = bool(u[5])
        v_wall = bool(u[6])
        over = u[7]
        dirt = u[8]
        ir_omni = u[10]
        btns = u[11]
        dist = u[12]
        ang = u[13]
        chg_code = u[14]
        v_mv = u[15]
        curr = u[16]
        temp = u[17]
        b_charge = u[18]
        b_cap = u[19]
        w_sig = u[20]
        cl_sig_l = u[21]
        cl_sig_fl = u[22]
        cl_sig_fr = u[23]
        cl_sig_r = u[24]
        chg_src = u[27]
        mode_code = u[28]
        enc_l = u[36]
        enc_r = u[37]
        lb = u[38]
        lb_l = u[39]
        lb_fl = u[40]
        lb_cl = u[41]
        lb_cr = u[42]
        lb_fr = u[43]
        lb_r = u[44]
        mc_l = u[45]
        mc_r = u[46]
        mc_mb = u[47]
        mc_sb = u[48]
        stasis_flag = bool(u[49])

        pct = (b_charge / b_cap * 100.0) if b_cap > 0 else 0.0

        return cls(
            timestamp=ts,
            bump_right=bool(b_w & 0x01),
            bump_left=bool(b_w & 0x02),
            wheel_drop_right=bool(b_w & 0x04),
            wheel_drop_left=bool(b_w & 0x08),
            wall=wall_det,
            wall_signal=w_sig,
            virtual_wall=v_wall,
            cliff_left=cl_l,
            cliff_front_left=cl_fl,
            cliff_front_right=cl_fr,
            cliff_right=cl_r,
            cliff_left_signal=cl_sig_l,
            cliff_front_left_signal=cl_sig_fl,
            cliff_front_right_signal=cl_sig_fr,
            cliff_right_signal=cl_sig_r,
            light_bumper_left=bool(lb & 0x01),
            light_bumper_front_left=bool(lb & 0x02),
            light_bumper_center_left=bool(lb & 0x04),
            light_bumper_center_right=bool(lb & 0x08),
            light_bumper_front_right=bool(lb & 0x10),
            light_bumper_right=bool(lb & 0x20),
            light_bumper_left_signal=lb_l,
            light_bumper_front_left_signal=lb_fl,
            light_bumper_center_left_signal=lb_cl,
            light_bumper_center_right_signal=lb_cr,
            light_bumper_front_right_signal=lb_fr,
            light_bumper_right_signal=lb_r,
            left_encoder=enc_l,
            right_encoder=enc_r,
            distance_mm=dist,
            angle_deg=ang,
            stasis=stasis_flag,
            charging_state=CHARGING_STATES.get(chg_code, f"Unknown ({chg_code})"),
            charging_state_code=chg_code,
            voltage_v=round(v_mv / 1000.0, 2),
            voltage_mv=v_mv,
            current_ma=curr,
            temperature_c=temp,
            battery_charge_mah=b_charge,
            battery_capacity_mah=b_cap,
            battery_percent=round(pct, 1),
            charging_source_internal=bool(chg_src & 0x01),
            charging_source_base=bool(chg_src & 0x02),
            left_motor_current_ma=mc_l,
            right_motor_current_ma=mc_r,
            main_brush_motor_current_ma=mc_mb,
            side_brush_motor_current_ma=mc_sb,
            left_wheel_overcurrent=bool(over & 0x10),
            right_wheel_overcurrent=bool(over & 0x08),
            main_brush_overcurrent=bool(over & 0x04),
            side_brush_overcurrent=bool(over & 0x01),
            dirt_detect=dirt,
            ir_char_omni=ir_omni,
            button_clean=bool(btns & 0x01),
            button_spot=bool(btns & 0x02),
            button_dock=bool(btns & 0x04),
            button_minute=bool(btns & 0x08),
            button_hour=bool(btns & 0x10),
            button_day=bool(btns & 0x20),
            button_schedule=bool(btns & 0x40),
            button_clock=bool(btns & 0x80),
            oi_mode=OI_MODES.get(mode_code, f"Unknown ({mode_code})"),
            oi_mode_code=mode_code,
        )


# --- Sound, Melodies, RTTTL & Morse Audio Engine ---

NOTE_OFFSETS: Dict[str, int] = {
    "c": 0, "c#": 1, "db": 1,
    "d": 2, "d#": 3, "eb": 3,
    "e": 4,
    "f": 5, "f#": 6, "gb": 6,
    "g": 7, "g#": 8, "ab": 8,
    "a": 9, "a#": 10, "bb": 10,
    "b": 11,
}

MORSE_CODE_DICT: Dict[str, str] = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".",
    "F": "..-.", "G": "--.", "H": "....", "I": "..", "J": ".---",
    "K": "-.-", "L": ".-..", "M": "--", "N": "-.", "O": "---",
    "P": ".--.", "Q": "--.-", "R": ".-.", "S": "...", "T": "-",
    "U": "..-", "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--",
    "Z": "--..", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
    "0": "-----", " ": " ", ".": ".-.-.-", ",": "--..--", "?": "..--..",
    "!": "-.-.--", "/": "-..-.", "-": "-....-", "(": "-.--.", ")": "-.--.-"
}

# Standard Preset Tunes (List of (MIDI note 31-127, duration 1-255 in 1/64s). Note 0 is rest)
PRESET_TUNES: Dict[str, List[Tuple[int, int]]] = {
    # Super Mario Bros Main Theme opening
    "mario": [
        (88, 8), (88, 8), (0, 8), (88, 8), (0, 8), (84, 8), (88, 8),
        (0, 8), (91, 16), (0, 16), (79, 16)
    ],
    # Star Wars Imperial March
    "imperial": [
        (67, 24), (67, 24), (67, 24), (63, 18), (70, 6),
        (67, 24), (63, 18), (70, 6), (67, 36)
    ],
    # Stadium Charge fanfare
    "charge": [
        (60, 10), (64, 10), (67, 10), (72, 16), (67, 10), (72, 28)
    ],
    # Legend of Zelda Secret Found chime
    "zelda": [
        (79, 7), (78, 7), (75, 7), (69, 7), (68, 7), (76, 7), (80, 7), (84, 16)
    ],
    # High-intensity warning alert siren
    "alert": [
        (84, 8), (72, 8), (84, 8), (72, 8), (84, 8), (72, 8), (84, 12)
    ],
    # Cheerful ascending chime
    "happy": [
        (60, 8), (64, 8), (67, 8), (72, 8), (76, 8), (79, 16)
    ],
    # Melancholy minor chime
    "sad": [
        (72, 16), (71, 16), (70, 16), (69, 24)
    ],
    # Nokia Ringtone snippet
    "nokia": [
        (88, 8), (86, 8), (78, 16), (80, 16),
        (84, 8), (83, 8), (74, 16), (76, 16),
        (81, 8), (79, 8), (71, 16), (73, 16), (76, 24)
    ],
    # Playful R2-D2 chirps
    "r2d2": [
        (84, 6), (96, 6), (91, 6), (103, 6), (88, 6), (93, 12)
    ],
}


def rtttl_to_notes(rtttl: str) -> List[Tuple[int, int]]:
    """
    Parse a Nokia RTTTL (Ring Tone Text Transfer Language) string into Roomba notes.
    Returns a list of (midi_note, duration_in_64ths) tuples.
    Rests are represented with midi_note = 0.
    """
    parts = rtttl.split(":")
    if len(parts) < 3:
        raise ValueError("Invalid RTTTL format: must contain name:defaults:notes")

    defaults = {}
    for item in parts[1].split(","):
        if "=" in item:
            k, v = item.strip().split("=", 1)
            try:
                defaults[k.strip().lower()] = int(v.strip())
            except ValueError:
                pass

    def_dur = defaults.get("d", 4)
    def_oct = defaults.get("o", 5)
    bpm = defaults.get("b", 120)

    notes: List[Tuple[int, int]] = []
    pattern = re.compile(r"^(\d+)?([a-g,p]#?|\.)(\.?)(\d+)?(\.?)", re.IGNORECASE)

    for chunk in parts[2].split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = pattern.match(chunk)
        if not m:
            continue
        d_str, note_str, dot1, oct_str, dot2 = m.groups()
        dur = int(d_str) if d_str else def_dur
        is_dotted = bool(dot1 or dot2)
        octave = int(oct_str) if oct_str else def_oct

        # Roomba duration: 64 units = 1 second.
        # Note duration seconds: (60.0 / bpm) * (4.0 / dur)
        note_sec = (60.0 / bpm) * (4.0 / dur)
        if is_dotted:
            note_sec *= 1.5
        dur_64 = max(1, min(255, round(note_sec * 64.0)))

        note_lower = note_str.lower()
        if note_lower == "p":
            notes.append((0, dur_64))
        elif note_lower in NOTE_OFFSETS:
            midi = 12 * (octave + 1) + NOTE_OFFSETS[note_lower]
            midi = max(31, min(127, midi))
            notes.append((midi, dur_64))

    return notes


def text_to_morse_notes(text: str, note: int = 76, dot_duration: int = 6) -> List[Tuple[int, int]]:
    """
    Convert an ASCII string to Morse code note sequences for Roomba playback.
    - Dot: 1 unit tone
    - Dash: 3 units tone
    - Element space: 1 unit rest
    - Letter space: 3 units rest
    - Word space: 7 units rest
    """
    notes: List[Tuple[int, int]] = []
    dot_dur = max(1, min(64, dot_duration))
    dash_dur = dot_dur * 3
    elem_gap = (0, dot_dur)
    char_gap = (0, dot_dur * 3)
    word_gap = (0, dot_dur * 7)

    words = text.upper().split(" ")
    for w_idx, word in enumerate(words):
        for c_idx, char in enumerate(word):
            code = MORSE_CODE_DICT.get(char, "")
            for s_idx, sym in enumerate(code):
                if sym == ".":
                    notes.append((note, dot_dur))
                elif sym == "-":
                    notes.append((note, dash_dur))
                if s_idx < len(code) - 1:
                    notes.append(elem_gap)
            if c_idx < len(word) - 1:
                notes.append(char_gap)
        if w_idx < len(words) - 1:
            notes.append(word_gap)

    return notes

