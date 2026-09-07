"""
Roomba 960 Hardware Sensor Monitor & Diagnostic Inspector.
Connects to Roomba 960 over micro-USB, queries all hardware sensors
via Open Interface Packet 100, and displays a categorized live dashboard or single snapshot.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from roomba.driver.client import RoombaClient
from roomba.driver.protocol import RoombaSensors
from roomba.driver.discovery import find_roomba_port

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def make_bar(val: int, max_val: int = 4095, width: int = 12) -> str:
    """Render a visual ASCII bar for analog sensor values."""
    ratio = min(1.0, max(0.0, val / max_val))
    filled = int(round(ratio * width))
    return f"[{'#' * filled}{'.' * (width - filled)}] {val:>4}"


def format_sensor_report(s: RoombaSensors) -> str:
    """Format a comprehensive sensor report string."""
    lines = []
    lines.append("=" * 72)
    lines.append("                  ROOMBA 960 HARDWARE SENSORS REPORT")
    lines.append("=" * 72)

    # 1. Bumpers & Wheel Drops
    lines.append(" [1] SAFETY: BUMPERS & WHEEL DROPS")
    lines.append(f"     Bumper Left      : {'[TRIGGERED]' if s.bump_left else 'OK (Open)'}")
    lines.append(f"     Bumper Right     : {'[TRIGGERED]' if s.bump_right else 'OK (Open)'}")
    lines.append(f"     Wheel Drop Left  : {'[DROPPED/ELEVATED]' if s.wheel_drop_left else 'OK (On Ground)'}")
    lines.append(f"     Wheel Drop Right : {'[DROPPED/ELEVATED]' if s.wheel_drop_right else 'OK (On Ground)'}")

    # 2. Cliff Sensors
    lines.append("\n [2] CLIFF DETECTION (INFRARED FLOOR SENSORS)")
    lines.append(f"     Left        : {'[CLIFF DETECTED]' if s.cliff_left else 'Floor OK'}  Signal: {make_bar(s.cliff_left_signal)}")
    lines.append(f"     Front Left  : {'[CLIFF DETECTED]' if s.cliff_front_left else 'Floor OK'}  Signal: {make_bar(s.cliff_front_left_signal)}")
    lines.append(f"     Front Right : {'[CLIFF DETECTED]' if s.cliff_front_right else 'Floor OK'}  Signal: {make_bar(s.cliff_front_right_signal)}")
    lines.append(f"     Right       : {'[CLIFF DETECTED]' if s.cliff_right else 'Floor OK'}  Signal: {make_bar(s.cliff_right_signal)}")

    # 3. Wall & Virtual Wall
    lines.append("\n [3] WALL & BEACON SENSORS")
    lines.append(f"     Right Wall Sensor: {'[DETECTED]' if s.wall else 'No Wall'}  Signal: {make_bar(s.wall_signal, max_val=1023)}")
    lines.append(f"     Virtual Wall/Dock: {'[BEACON ACTIVE]' if s.virtual_wall else 'None'}")
    lines.append(f"     IR Omni Receiver : 0x{s.ir_char_omni:02X} ({s.ir_char_omni})")

    # 4. Light Bumper Proximity Array (6 Zones across front bumper)
    lines.append("\n [4] LIGHT BUMPER PROXIMITY ARRAY (6 ZONES)")
    lines.append(f"     Left         : {'[DETECT]' if s.light_bumper_left else 'Clear   '}  Signal: {make_bar(s.light_bumper_left_signal)}")
    lines.append(f"     Front Left   : {'[DETECT]' if s.light_bumper_front_left else 'Clear   '}  Signal: {make_bar(s.light_bumper_front_left_signal)}")
    lines.append(f"     Center Left  : {'[DETECT]' if s.light_bumper_center_left else 'Clear   '}  Signal: {make_bar(s.light_bumper_center_left_signal)}")
    lines.append(f"     Center Right : {'[DETECT]' if s.light_bumper_center_right else 'Clear   '}  Signal: {make_bar(s.light_bumper_center_right_signal)}")
    lines.append(f"     Front Right  : {'[DETECT]' if s.light_bumper_front_right else 'Clear   '}  Signal: {make_bar(s.light_bumper_front_right_signal)}")
    lines.append(f"     Right        : {'[DETECT]' if s.light_bumper_right else 'Clear   '}  Signal: {make_bar(s.light_bumper_right_signal)}")

    # 5. Encoders & Odometry
    lines.append("\n [5] WHEEL ENCODERS & ODOMETRY")
    lines.append(f"     Left Wheel Encoder : {s.left_encoder:>5} ticks")
    lines.append(f"     Right Wheel Encoder: {s.right_encoder:>5} ticks")
    lines.append(f"     Distance Traveled  : {s.distance_mm:>5} mm (since last query)")
    lines.append(f"     Angle Rotated      : {s.angle_deg:>5} deg (since last query)")
    lines.append(f"     Stasis (Progress)  : {'OK (Moving)' if s.stasis else 'Normal / Stationary'}")

    # 6. Battery & Power System
    lines.append("\n [6] BATTERY & POWER SYSTEM")
    lines.append(f"     State of Charge    : {s.battery_percent:>5.1f}%  ({s.battery_charge_mah} / {s.battery_capacity_mah} mAh)")
    lines.append(f"     Battery Voltage    : {s.voltage_v:>5.2f} V ({s.voltage_mv} mV)")
    lines.append(f"     Current Flow       : {s.current_ma:>5} mA {'(Discharging)' if s.current_ma < 0 else '(Charging)' if s.current_ma > 0 else ''}")
    lines.append(f"     Temperature        : {s.temperature_c:>5} °C")
    lines.append(f"     Charging Mode      : {s.charging_state} (Code {s.charging_state_code})")
    lines.append(f"     Charging Sources   : Internal={s.charging_source_internal}, HomeBase/Dock={s.charging_source_base}")

    # 7. Motor Currents & Overcurrent Alerts
    lines.append("\n [7] MOTOR CURRENTS & OVERCURRENT MONITORS")
    lines.append(f"     Left Drive Motor   : {s.left_motor_current_ma:>4} mA  | Overcurrent: {s.left_wheel_overcurrent}")
    lines.append(f"     Right Drive Motor  : {s.right_motor_current_ma:>4} mA  | Overcurrent: {s.right_wheel_overcurrent}")
    lines.append(f"     Main Brush Motor   : {s.main_brush_motor_current_ma:>4} mA  | Overcurrent: {s.main_brush_overcurrent}")
    lines.append(f"     Side Brush Motor   : {s.side_brush_motor_current_ma:>4} mA  | Overcurrent: {s.side_brush_overcurrent}")

    # 8. User Interface & Environment
    lines.append("\n [8] BUTTONS, CLEANING & OI STATUS")
    lines.append(f"     Buttons Pressed    : Clean={s.button_clean}, Spot={s.button_spot}, Dock={s.button_dock}")
    lines.append(f"     Dirt Detect Sensor : {s.dirt_detect:>3} / 255")
    lines.append(f"     Current OI Mode    : {s.oi_mode} (Code {s.oi_mode_code})")
    lines.append("=" * 72)
    return "\n".join(lines)


async def run_monitor(
    port: Optional[str] = None,
    baudrate: int = 115200,
    once: bool = False,
    rate_hz: float = 5.0,
) -> None:
    target_port = port or find_roomba_port()
    if not target_port:
        print("[!] Error: Could not locate Roomba serial port.")
        sys.exit(1)

    print(f"Connecting to Roomba on {target_port} at {baudrate} baud...")
    client = RoombaClient(port=target_port, baudrate=baudrate)

    try:
        await client.connect()
        await client.safe_mode()
        await asyncio.sleep(0.1)

        interval = 1.0 / max(0.5, min(20.0, rate_hz))

        if once:
            sensors = await client.get_sensors()
            print(format_sensor_report(sensors))
            return

        print(f"\nLive monitoring started at {rate_hz:.1f} Hz. Press Ctrl+C to stop.\n")
        time.sleep(1.0)

        while True:
            t0 = time.monotonic()
            sensors = await client.get_sensors()
            os.system("cls" if sys.platform == "win32" else "clear")
            print(format_sensor_report(sensors))
            print(f"Updated at {time.strftime('%H:%M:%S')} (Rate: {rate_hz} Hz). Press Ctrl+C to exit.")

            elapsed = time.monotonic() - t0
            sleep_time = max(0.01, interval - elapsed)
            await asyncio.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n\nMonitoring stopped by user.")
    except Exception as e:
        print(f"\n[!] Sensor monitor error: {e}")
    finally:
        await client.disconnect()
        print("Disconnected cleanly.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Roomba 960 Hardware Sensor Monitor.")
    parser.add_argument("--port", type=str, default=None, help="Serial port (auto-detected if omitted)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--once", action="store_true", help="Print single report snapshot and exit")
    parser.add_argument("--rate", type=float, default=5.0, help="Refresh rate in Hz (default: 5.0)")
    args = parser.parse_args()

    asyncio.run(run_monitor(port=args.port, baudrate=args.baud, once=args.once, rate_hz=args.rate))


if __name__ == "__main__":
    main()
