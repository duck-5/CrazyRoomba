"""
Asynchronous Roomba Open Interface (OI) Client.
Handles serial communication over USB/serial on Windows and Linux/Raspberry Pi.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from typing import Optional, Dict, Any, List, Tuple, Sequence

try:
    import serial_asyncio
except ImportError:
    serial_asyncio = None

from .protocol import (
    RoombaOpcode,
    RoombaSensorPacket,
    RoombaSensors,
    CHARGING_STATES,
    PRESET_TUNES,
    rtttl_to_notes,
    text_to_morse_notes,
)
from .discovery import find_roomba_port

logger = logging.getLogger("roomba.driver.client")


class RoombaClient:
    """Asynchronous client for Roomba 960 (and compatible OI robots)."""

    def __init__(self, port: Optional[str] = None, baudrate: int = 115200, timeout: float = 2.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._mode = "Off"
        self._lock = asyncio.Lock()

        # Odometry & Kinematics State
        self.total_distance_mm: float = 0.0
        self.total_angle_deg: float = 0.0
        self._prev_encoder_left: Optional[int] = None
        self._prev_encoder_right: Optional[int] = None

    @property
    def is_connected(self) -> bool:
        return self._connected and self.writer is not None

    @property
    def mode(self) -> str:
        return self._mode

    async def connect(self) -> None:
        """Establish serial connection to Roomba."""
        if serial_asyncio is None:
            raise RuntimeError("pyserial-asyncio is required. Install with: pip install pyserial-asyncio")

        if not self.port:
            detected = find_roomba_port()
            if not detected:
                raise ConnectionError("Could not automatically locate Roomba serial port. Please specify port manually.")
            self.port = detected

        logger.info(f"Connecting to Roomba on {self.port} at {self.baudrate} baud...")
        self.reader, self.writer = await serial_asyncio.open_serial_connection(
            url=self.port, baudrate=self.baudrate
        )
        self._connected = True
        logger.info(f"Serial port {self.port} opened.")
        await asyncio.sleep(0.1)

    async def disconnect(self) -> None:
        """Safely stop motors and close serial connection."""
        if not self._connected:
            return

        try:
            logger.info("Stopping motors and closing connection...")
            await self.stop()
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.warning(f"Error while stopping motors during disconnect: {e}")

        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception as e:
                logger.debug(f"Writer close error: {e}")

        self.reader = None
        self.writer = None
        self._connected = False
        self._mode = "Off"
        logger.info("Disconnected from Roomba.")

    async def __aenter__(self) -> "RoombaClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()

    async def send_command(self, data: bytes | bytearray | list[int]) -> None:
        """Send raw bytes to the Roomba."""
        if not self.is_connected or self.writer is None:
            raise ConnectionError("Not connected to Roomba")

        raw = bytes(data)
        self.writer.write(raw)
        await self.writer.drain()

    async def read_bytes(self, num_bytes: int, timeout: Optional[float] = None) -> bytes:
        """Read an exact number of bytes from the serial connection with timeout."""
        if not self.is_connected or self.reader is None:
            raise ConnectionError("Not connected to Roomba")

        t = timeout if timeout is not None else self.timeout
        try:
            data = await asyncio.wait_for(self.reader.readexactly(num_bytes), timeout=t)
            return data
        except asyncio.TimeoutError:
            raise TimeoutError(f"Timed out waiting for {num_bytes} bytes from Roomba after {t}s")

    def flush_input_buffer(self) -> None:
        """Purge any pending or framing-offset bytes from the asyncio stream buffer."""
        if self.reader and hasattr(self.reader, "_buffer") and self.reader._buffer:
            self.reader._buffer.clear()

    # --- OI Modes ---

    async def start(self) -> None:
        """Send Start command (Opcode 128). Changes mode to Passive."""
        async with self._lock:
            logger.info("Sending START command (128)...")
            await self.send_command([RoombaOpcode.START])
            await asyncio.sleep(0.05)
            self._mode = "Passive"

    async def safe_mode(self) -> None:
        """Put Roomba into Safe Mode (Opcode 131). Retains cliff/drop safety stops."""
        await self.start()
        async with self._lock:
            logger.info("Sending SAFE mode command (131)...")
            await self.send_command([RoombaOpcode.SAFE])
            await asyncio.sleep(0.05)
            self._mode = "Safe"

    async def full_mode(self) -> None:
        """Put Roomba into Full Mode (Opcode 132). Unrestricted motor control."""
        await self.start()
        async with self._lock:
            logger.info("Sending FULL mode command (132)...")
            await self.send_command([RoombaOpcode.FULL])
            await asyncio.sleep(0.05)
            self._mode = "Full"

    async def stop_oi(self) -> None:
        """Send Stop command (Opcode 173) to terminate Open Interface mode."""
        async with self._lock:
            logger.info("Sending STOP command (173)...")
            await self.send_command([RoombaOpcode.STOP])
            await asyncio.sleep(0.05)
            self._mode = "Off"

    async def clean(self) -> None:
        """Send Clean command (Opcode 135) to start default cleaning cycle."""
        async with self._lock:
            logger.info("Sending CLEAN command (135)...")
            await self.send_command([RoombaOpcode.CLEAN])
            self._mode = "Passive"

    async def spot(self) -> None:
        """Send Spot Clean command (Opcode 134)."""
        async with self._lock:
            logger.info("Sending SPOT command (134)...")
            await self.send_command([RoombaOpcode.SPOT])
            self._mode = "Passive"

    async def seek_dock(self) -> None:
        """Send Seek Dock command (Opcode 143) to guide Roomba to charging dock."""
        async with self._lock:
            logger.info("Sending SEEK_DOCK command (143)...")
            await self.send_command([RoombaOpcode.SEEK_DOCK])
            self._mode = "Passive"

    async def power_off(self) -> None:
        """Send Power command (Opcode 133) to put Roomba into sleep/power-down mode."""
        async with self._lock:
            logger.info("Sending POWER command (133)...")
            await self.send_command([RoombaOpcode.POWER])
            self._mode = "Off"

    async def define_song(self, song_number: int, notes: Sequence[Tuple[int, int]]) -> None:
        """
        Define a song sequence with Opcode 140 (Song).
        - song_number: 0 to 15 (slots 0-4 are standard across all OI versions).
        - notes: list of (note_number, duration_64ths) tuples, up to 16 notes.
          Note number 31-127 is audible pitch; 0 (or < 31) acts as musical rest.
          Duration is in 1/64ths of a second (1 to 255).
        """
        if not (0 <= song_number <= 15):
            raise ValueError(f"Song number must be 0-15, got {song_number}")
        if not (1 <= len(notes) <= 16):
            raise ValueError(f"Song length must be 1-16 notes, got {len(notes)}")

        payload: List[int] = [RoombaOpcode.SONG, song_number, len(notes)]
        for pitch, dur in notes:
            p = max(0, min(127, int(pitch)))
            d = max(1, min(255, int(dur)))
            payload.extend([p, d])

        async with self._lock:
            await self.send_command(payload)
            await asyncio.sleep(0.02)
            self.flush_input_buffer()

    async def play_song(self, song_number: int) -> None:
        """Play a previously defined song slot with Opcode 141 (Play)."""
        if not (0 <= song_number <= 15):
            raise ValueError(f"Song number must be 0-15, got {song_number}")
        async with self._lock:
            await self.send_command([RoombaOpcode.PLAY, song_number])
            await asyncio.sleep(0.02)
            self.flush_input_buffer()

    async def play_tune(self, notes: Sequence[Tuple[int, int]], song_slot: int = 0) -> None:
        """
        Play an arbitrary sequence of notes.
        If more than 16 notes, automatically chunks them into 16-note batches,
        uploads to song_slot, plays, and waits for completion before sending the next chunk.
        """
        if not notes:
            return

        chunk_size = 16
        for i in range(0, len(notes), chunk_size):
            chunk = list(notes[i:i + chunk_size])
            await self.define_song(song_slot, chunk)
            await self.play_song(song_slot)
            total_duration_sec = sum(dur for _, dur in chunk) / 64.0
            await asyncio.sleep(total_duration_sec + 0.05)

    async def beep(self, note: int = 72, duration: int = 16) -> None:
        """Play a musical beep using Song (140) and Play (141) opcodes."""
        await self.define_song(0, [(note, duration)])
        await self.play_song(0)

    async def play_tune_preset(self, preset_name: str) -> None:
        """Play a predefined tune by name (e.g. mario, imperial, zelda, etc.)."""
        notes = PRESET_TUNES.get(preset_name.lower())
        if not notes:
            raise ValueError(f"Unknown preset tune: {preset_name}. Available: {list(PRESET_TUNES.keys())}")
        await self.play_tune(notes)

    async def play_rtttl(self, rtttl_string: str) -> None:
        """Play a Nokia RTTTL ringtone string on the Roomba speaker."""
        notes = rtttl_to_notes(rtttl_string)
        await self.play_tune(notes)

    async def play_morse(self, text: str, note: int = 76, dot_duration: int = 6) -> None:
        """Transmit text over the Roomba speaker as Morse code beeps."""
        notes = text_to_morse_notes(text, note=note, dot_duration=dot_duration)
        await self.play_tune(notes)

    # --- Motor & Movement Commands ---

    async def drive_direct(self, right_velocity_mm_s: int, left_velocity_mm_s: int) -> None:
        """Drive wheels independently in mm/s (-500 to 500). Opcode 145."""
        r_vel = max(-500, min(500, int(right_velocity_mm_s)))
        l_vel = max(-500, min(500, int(left_velocity_mm_s)))
        payload = struct.pack(">Bhh", RoombaOpcode.DRIVE_DIRECT, r_vel, l_vel)
        async with self._lock:
            await self.send_command(payload)

    async def stop(self) -> None:
        """Stop both wheel motors immediately."""
        await self.drive_direct(0, 0)

    async def move_wheel(
        self,
        right_speed_mm_s: int = 0,
        left_speed_mm_s: int = 0,
        duration_s: float = 1.0,
    ) -> None:
        """Move wheels for a specified duration and automatically stop afterwards."""
        try:
            await self.drive_direct(right_speed_mm_s, left_speed_mm_s)
            await asyncio.sleep(duration_s)
        finally:
            await self.stop()

    # --- Sensor Queries ---

    async def query_sensor(self, packet_id: int, byte_length: int) -> bytes:
        """Query a single sensor packet ID and return raw response bytes."""
        async with self._lock:
            self.flush_input_buffer()
            await self.send_command([RoombaOpcode.SENSORS, packet_id])
            return await self.read_bytes(byte_length)

    def reset_odometry(self) -> None:
        """Reset cumulative distance, angle, and encoder baselines to zero."""
        self.total_distance_mm = 0.0
        self.total_angle_deg = 0.0
        self._prev_encoder_left = None
        self._prev_encoder_right = None
        logger.info("Odometry counters reset to zero.")

    def _update_odometry(self, enc_left: int, enc_right: int) -> Tuple[float, float]:
        """
        Update persistent cumulative odometry from 16-bit raw encoder ticks.
        Returns (delta_dist_mm, delta_angle_deg).

        Roomba 960 Kinematics:
        - Wheel diameter: 72.0 mm
        - Wheelbase: 235.0 mm
        - Encoder ticks per wheel revolution: 508.8
        - Distance per tick = (pi * 72.0) / 508.8 ~= 0.444563 mm/tick
        """
        if self._prev_encoder_left is None or self._prev_encoder_right is None:
            self._prev_encoder_left = enc_left
            self._prev_encoder_right = enc_right
            return (0.0, 0.0)

        # 16-bit unsigned tick difference with rollover handling
        delta_l_ticks = (enc_left - self._prev_encoder_left + 32768) % 65536 - 32768
        delta_r_ticks = (enc_right - self._prev_encoder_right + 32768) % 65536 - 32768

        self._prev_encoder_left = enc_left
        self._prev_encoder_right = enc_right

        # Ignore wild encoder jumps (e.g. UART noise or framing offset glitch)
        if abs(delta_l_ticks) > 5000 or abs(delta_r_ticks) > 5000:
            logger.warning(f"Ignoring wild encoder jump: delta_L={delta_l_ticks}, delta_R={delta_r_ticks}")
            return (0.0, 0.0)

        MM_PER_TICK = 0.444563
        WHEELBASE_MM = 235.0

        delta_l_mm = delta_l_ticks * MM_PER_TICK
        delta_r_mm = delta_r_ticks * MM_PER_TICK

        # Average forward distance
        delta_dist_mm = (delta_r_mm + delta_l_mm) / 2.0

        # Differential rotation angle (degrees, counter-clockwise positive)
        delta_angle_deg = ((delta_r_mm - delta_l_mm) / WHEELBASE_MM) * (180.0 / 3.141592653589793)

        self.total_distance_mm += delta_dist_mm
        self.total_angle_deg += delta_angle_deg

        return (delta_dist_mm, delta_angle_deg)

    @staticmethod
    def _is_valid_telemetry(s: RoombaSensors) -> bool:
        """Verify physical plausibility of unpacked Roomba telemetry."""
        if not (10.0 <= s.voltage_v <= 18.5):
            return False
        if not (-10 <= s.temperature_c <= 65):
            return False
        if s.charging_state_code not in CHARGING_STATES:
            return False
        return True

    async def get_sensors(self) -> RoombaSensors:
        """Query complete 80-byte Packet 100 containing all sensors in one atomic call."""
        raw = await self.query_sensor(*RoombaSensorPacket.ALL_SENSORS_100)
        s = RoombaSensors.from_bytes(raw)
        if self._is_valid_telemetry(s):
            self._update_odometry(s.left_encoder, s.right_encoder)
        return s

    async def get_sensors_dict(self) -> Dict[str, Any]:
        """Query all sensors and return as a nested dictionary."""
        sensors = await self.get_sensors()
        return sensors.to_dict()

    async def get_voltage(self) -> int:
        raw = await self.query_sensor(*RoombaSensorPacket.VOLTAGE)
        return struct.unpack(">H", raw)[0]

    async def get_current(self) -> int:
        raw = await self.query_sensor(*RoombaSensorPacket.CURRENT)
        return struct.unpack(">h", raw)[0]

    async def get_battery_charge(self) -> int:
        raw = await self.query_sensor(*RoombaSensorPacket.BATTERY_CHARGE)
        return struct.unpack(">H", raw)[0]

    async def get_battery_capacity(self) -> int:
        raw = await self.query_sensor(*RoombaSensorPacket.BATTERY_CAPACITY)
        return struct.unpack(">H", raw)[0]

    async def get_charging_state(self) -> int:
        raw = await self.query_sensor(*RoombaSensorPacket.CHARGING_STATE)
        return raw[0]

    async def get_bumps_and_wheel_drops(self) -> Dict[str, bool]:
        raw = await self.query_sensor(*RoombaSensorPacket.BUMPS_WHEEL_DROPS)
        val = raw[0]
        return {
            "bump_right": bool(val & 0x01),
            "bump_left": bool(val & 0x02),
            "wheel_drop_right": bool(val & 0x04),
            "wheel_drop_left": bool(val & 0x08),
        }

    async def get_telemetry(self) -> Dict[str, Any]:
        """Fast telemetry summary with comprehensive sensor dictionary."""
        try:
            s = await self.get_sensors()
            return {
                "port": self.port,
                "connected": True,
                "mode": self._mode,
                "oi_mode": s.oi_mode,
                "voltage_v": s.voltage_v,
                "voltage_mv": s.voltage_mv,
                "current_ma": s.current_ma,
                "battery_charge_mah": s.battery_charge_mah,
                "battery_capacity_mah": s.battery_capacity_mah,
                "battery_percent": s.battery_percent,
                "temperature_c": s.temperature_c,
                "charging_state_code": s.charging_state_code,
                "charging_state": s.charging_state,
                "bumps_and_drops": {
                    "bump_right": s.bump_right,
                    "bump_left": s.bump_left,
                    "wheel_drop_right": s.wheel_drop_right,
                    "wheel_drop_left": s.wheel_drop_left,
                },
                "cliffs": {
                    "cliff_left": s.cliff_left,
                    "cliff_front_left": s.cliff_front_left,
                    "cliff_front_right": s.cliff_front_right,
                    "cliff_right": s.cliff_right,
                },
                "wall": {
                    "wall": s.wall,
                    "virtual_wall": s.virtual_wall,
                },
                "light_bumpers": {
                    "left": s.light_bumper_left,
                    "front_left": s.light_bumper_front_left,
                    "center_left": s.light_bumper_center_left,
                    "center_right": s.light_bumper_center_right,
                    "front_right": s.light_bumper_front_right,
                    "right": s.light_bumper_right,
                },
                "encoders": {
                    "left": s.left_encoder,
                    "right": s.right_encoder,
                    "distance_mm": round(self.total_distance_mm, 1),
                    "angle_deg": round(self.total_angle_deg, 1),
                    "heading_deg": round(self.total_angle_deg % 360, 1),
                    "delta_distance_mm": s.distance_mm,
                    "delta_angle_deg": s.angle_deg,
                },
            }
        except Exception as e:
            logger.warning(f"Packet 100 query failed ({e}), falling back to individual queries")
            v_mv = await self.get_voltage()
            c_ma = await self.get_current()
            b_chg = await self.get_battery_charge()
            b_cap = await self.get_battery_capacity()
            st = await self.get_charging_state()
            drops = await self.get_bumps_and_wheel_drops()
            pct = round((b_chg / b_cap * 100.0), 1) if b_cap > 0 else 0.0
            return {
                "port": self.port,
                "connected": True,
                "mode": self._mode,
                "oi_mode": self._mode,
                "voltage_v": round(v_mv / 1000.0, 2),
                "voltage_mv": v_mv,
                "current_ma": c_ma,
                "battery_charge_mah": b_chg,
                "battery_capacity_mah": b_cap,
                "battery_percent": pct,
                "temperature_c": 25,
                "charging_state_code": st,
                "charging_state": CHARGING_STATES.get(st, f"Unknown ({st})"),
                "bumps_and_drops": drops,
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
                    "distance_mm": round(self.total_distance_mm, 1),
                    "angle_deg": round(self.total_angle_deg, 1),
                    "heading_deg": round(self.total_angle_deg % 360, 1),
                    "delta_distance_mm": 0,
                    "delta_angle_deg": 0,
                },
            }
