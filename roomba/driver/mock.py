"""
Mock Roomba Client for simulation, offline testing, and hardware fallback.
Simulates Roomba 960 Open Interface behavior, sensors, battery drain, and safety interlocks.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, Any, Optional, List, Tuple, Sequence

logger = logging.getLogger("roomba.driver.mock")


class MockRoombaClient:
    """Drop-in mock client for RoombaClient."""

    def __init__(self, port: str = "MOCK", baudrate: int = 115200, timeout: float = 2.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._connected = False
        self._mode = "Off"
        self._lock = asyncio.Lock()
        self.songs: Dict[int, List[Tuple[int, int]]] = {}

        # Simulated state
        self.voltage_mv = 16200
        self.battery_capacity_mah = 2600
        self.battery_charge_mah = 2350
        self.charging_state = "Not Charging"
        self.charging_state_code = 0
        self.temperature_c = 26

        # Motors & Motion
        self.left_velocity = 0
        self.right_velocity = 0
        self.distance_mm = 0
        self.angle_deg = 0
        self.left_encoder = 0
        self.right_encoder = 0

        # Sensors
        self.bump_left = False
        self.bump_right = False
        self.wheel_drop_left = False
        self.wheel_drop_right = False
        self.cliff_left = False
        self.cliff_front_left = False
        self.cliff_front_right = False
        self.cliff_right = False
        self.wall = False
        self.virtual_wall = False
        self.light_bumper_left = False
        self.light_bumper_front_left = False
        self.light_bumper_center_left = False
        self.light_bumper_center_right = False
        self.light_bumper_front_right = False
        self.light_bumper_right = False

        self._last_sim_time = time.monotonic()

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def mode(self) -> str:
        return self._mode

    async def connect(self) -> None:
        self._connected = True
        self._last_sim_time = time.monotonic()
        logger.info(f"Mock Roomba connected on {self.port}")
        await asyncio.sleep(0.05)

    async def disconnect(self) -> None:
        await self.stop()
        self._connected = False
        self._mode = "Off"
        logger.info("Mock Roomba disconnected")

    async def __aenter__(self) -> "MockRoombaClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()

    async def start(self) -> None:
        self._mode = "Passive"
        await asyncio.sleep(0.02)

    async def safe_mode(self) -> None:
        self._mode = "Safe"
        await asyncio.sleep(0.02)

    async def full_mode(self) -> None:
        self._mode = "Full"
        await asyncio.sleep(0.02)

    async def stop_oi(self) -> None:
        await self.stop()
        self._mode = "Off"
        await asyncio.sleep(0.02)

    async def clean(self) -> None:
        self._mode = "Passive"

    async def spot(self) -> None:
        self._mode = "Passive"

    async def seek_dock(self) -> None:
        self._mode = "Passive"
        self.charging_state = "Full Charging"
        self.charging_state_code = 2

    async def power_off(self) -> None:
        await self.stop()
        self._mode = "Off"

    async def define_song(self, song_number: int, notes: Sequence[Tuple[int, int]]) -> None:
        self.songs[song_number] = [(int(p), int(d)) for p, d in notes]
        logger.info(f"Mock: Defined song {song_number} with {len(notes)} notes")

    async def play_song(self, song_number: int) -> None:
        song = self.songs.get(song_number, [])
        logger.info(f"Mock: Playing song {song_number} ({len(song)} notes)")

    async def play_tune(self, notes: Sequence[Tuple[int, int]], song_slot: int = 0) -> None:
        chunk_size = 16
        chunks = [list(notes[i:i + chunk_size]) for i in range(0, len(notes), chunk_size)]
        if not chunks:
            return
        slot = song_slot
        for chunk in chunks:
            await self.define_song(slot, chunk)
            await self.play_song(slot)
            total_dur = sum(dur for _, dur in chunk) / 64.0
            await asyncio.sleep(min(0.01, total_dur))
            slot = 1 if slot == 0 else 0


    async def beep(self, note: int = 72, duration: int = 16) -> None:
        logger.info(f"Mock: Beep! Note={note}, Duration={duration}")
        await self.define_song(0, [(note, duration)])
        await self.play_song(0)

    async def drive_direct(self, right_velocity_mm_s: int, left_velocity_mm_s: int) -> None:
        self._update_sim()
        if self._mode == "Safe":
            if self.wheel_drop_left or self.wheel_drop_right or self.cliff_left or self.cliff_right:
                self.left_velocity = 0
                self.right_velocity = 0
                return

        self.right_velocity = max(-500, min(500, int(right_velocity_mm_s)))
        self.left_velocity = max(-500, min(500, int(left_velocity_mm_s)))

    async def stop(self) -> None:
        self.left_velocity = 0
        self.right_velocity = 0

    async def move_wheel(
        self,
        right_speed_mm_s: int = 0,
        left_speed_mm_s: int = 0,
        duration_s: float = 1.0,
    ) -> None:
        await self.drive_direct(right_speed_mm_s, left_speed_mm_s)
        try:
            await asyncio.sleep(duration_s)
        finally:
            await self.stop()

    def set_sensor(self, sensor_name: str, value: Any) -> None:
        if hasattr(self, sensor_name):
            setattr(self, sensor_name, value)

    def _update_sim(self) -> None:
        now = time.monotonic()
        dt = now - self._last_sim_time
        self._last_sim_time = now

        if dt <= 0:
            return

        is_moving = self.left_velocity != 0 or self.right_velocity != 0
        current_ma = -200
        if is_moving:
            avg_speed = (abs(self.left_velocity) + abs(self.right_velocity)) / 2.0
            motor_current = int(avg_speed * 1.5)
            current_ma -= motor_current

            avg_v = (self.left_velocity + self.right_velocity) / 2.0
            dist_delta = int(avg_v * dt)
            self.distance_mm += dist_delta
            self.left_encoder = (self.left_encoder + int(self.left_velocity * dt * 2)) % 65536
            self.right_encoder = (self.right_encoder + int(self.right_velocity * dt * 2)) % 65536

            diff_v = (self.right_velocity - self.left_velocity)
            ang_delta = int((diff_v / 235.0) * (180.0 / 3.14159) * dt)
            self.angle_deg = (self.angle_deg + ang_delta) % 360

        drain_mah = (abs(current_ma) / 3600.0) * dt
        self.battery_charge_mah = max(0.0, self.battery_charge_mah - drain_mah)

        base_v = 15800 + int((self.battery_charge_mah / self.battery_capacity_mah) * 800)
        load_sag = 300 if is_moving else 0
        self.voltage_mv = max(13000, base_v - load_sag)

    def reset_odometry(self) -> None:
        """Reset mock odometry and encoder counters to zero."""
        self.distance_mm = 0
        self.angle_deg = 0
        self.left_encoder = 0
        self.right_encoder = 0

    async def play_tune(self, notes: Any, song_slot: int = 0) -> None:
        logger.info(f"Mock: Playing {len(notes)} notes on slot {song_slot}")

    async def play_tune_preset(self, preset_name: str) -> None:
        logger.info(f"Mock: Playing preset tune '{preset_name}'")

    async def play_rtttl(self, rtttl_string: str) -> None:
        logger.info(f"Mock: Playing RTTTL '{rtttl_string}'")

    async def play_morse(self, text: str, note: int = 76, dot_duration: int = 6) -> None:
        logger.info(f"Mock: Playing Morse code for '{text}'")

    async def get_telemetry(self) -> Dict[str, Any]:
        self._update_sim()
        pct = round((self.battery_charge_mah / self.battery_capacity_mah * 100.0), 1) if self.battery_capacity_mah > 0 else 0.0
        current_ma = -220 - int((abs(self.left_velocity) + abs(self.right_velocity)) * 0.8)

        return {
            "port": self.port,
            "connected": self._connected,
            "is_mock": True,
            "mode": self._mode,
            "oi_mode": self._mode,
            "voltage_v": round(self.voltage_mv / 1000.0, 2),
            "voltage_mv": self.voltage_mv,
            "current_ma": current_ma,
            "battery_charge_mah": int(self.battery_charge_mah),
            "battery_capacity_mah": self.battery_capacity_mah,
            "battery_percent": pct,
            "temperature_c": self.temperature_c,
            "charging_state_code": self.charging_state_code,
            "charging_state": self.charging_state,
            "bumps_and_drops": {
                "bump_right": self.bump_right,
                "bump_left": self.bump_left,
                "wheel_drop_right": self.wheel_drop_right,
                "wheel_drop_left": self.wheel_drop_left,
            },
            "cliffs": {
                "cliff_left": self.cliff_left,
                "cliff_front_left": self.cliff_front_left,
                "cliff_front_right": self.cliff_front_right,
                "cliff_right": self.cliff_right,
            },
            "wall": {
                "wall": self.wall,
                "virtual_wall": self.virtual_wall,
            },
            "light_bumpers": {
                "left": self.light_bumper_left,
                "front_left": self.light_bumper_front_left,
                "center_left": self.light_bumper_center_left,
                "center_right": self.light_bumper_center_right,
                "front_right": self.light_bumper_front_right,
                "right": self.light_bumper_right,
            },
            "encoders": {
                "left": self.left_encoder,
                "right": self.right_encoder,
                "distance_mm": round(self.distance_mm, 1),
                "angle_deg": round(self.angle_deg, 1),
                "heading_deg": round(self.angle_deg % 360, 1),
                "delta_distance_mm": 0,
                "delta_angle_deg": 0,
            },
            "velocities": {
                "left": self.left_velocity,
                "right": self.right_velocity,
            },
        }
