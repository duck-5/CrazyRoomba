"""
Hardware connection and telemetry verifier for Roomba 960.
Scans serial ports, establishes connection, initializes Safe Mode, and reads live sensors.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from roomba.driver.client import RoombaClient
from roomba.driver.discovery import find_roomba_port, list_serial_ports


def print_ports():
    print("--- Detected Serial Ports ---")
    ports = list_serial_ports()
    if not ports:
        print("  No serial ports found!")
        return

    for p in ports:
        tag = "⭐ [ROOMBA 960]" if p["is_roomba"] else ""
        vid_pid = f"VID:PID={p['vid']}:{p['pid']}" if p["vid"] and p["pid"] else "N/A"
        print(f"  * {p['device']} {tag}: {p['description']} [{vid_pid}]")
    print("-----------------------------\n")


async def run_verification(port: str | None = None, baudrate: int = 115200):
    print("=" * 60)
    print("       Roomba 960 Hardware Connection & Telemetry Verifier")
    print("=" * 60)

    print_ports()

    target_port = port or find_roomba_port()
    if not target_port:
        print("[!] Error: Could not find any Roomba or USB serial port.")
        print("   Please check your micro-USB cable and ensure the Roomba is powered on.")
        if sys.platform.startswith("linux"):
            print("   Tip for Linux/Raspberry Pi: Ensure your user is in the dialout group:")
            print("     sudo usermod -a -G dialout $USER")
        sys.exit(1)

    print(f"Connecting to target port: {target_port} at {baudrate} baud...")
    client = RoombaClient(port=target_port, baudrate=baudrate, timeout=2.5)

    try:
        await client.connect()
        print(f"[OK] Serial connection opened on {target_port}.")

        print("Initializing Open Interface (Start [128] -> Safe Mode [131])...")
        await client.safe_mode()
        await asyncio.sleep(0.2)
        print("[OK] Roomba entered Safe Mode successfully.")

        print("\nQuerying live sensor telemetry...")
        telemetry = await client.get_telemetry()

        print("\n" + "=" * 60)
        print("                 ROOMBA TELEMETRY REPORT")
        print("=" * 60)
        print(f"  Connection Status  : ONLINE (Two-way communication verified)")
        print(f"  Platform           : {sys.platform}")
        print(f"  Serial Port        : {telemetry['port']}")
        print(f"  OI Mode            : {telemetry.get('oi_mode', telemetry.get('mode'))}")
        print(f"  Battery Voltage    : {telemetry['voltage_v']} V ({telemetry['voltage_mv']} mV)")
        print(f"  Current Draw       : {telemetry['current_ma']} mA")
        print(f"  Battery Charge     : {telemetry['battery_charge_mah']} / {telemetry['battery_capacity_mah']} mAh ({telemetry['battery_percent']}%)")
        print(f"  Temperature        : {telemetry['temperature_c']} °C")
        print(f"  Charging State     : {telemetry['charging_state']}")

        drops = telemetry["bumps_and_drops"]
        print(f"  Wheel Drops        : Left={drops['wheel_drop_left']}, Right={drops['wheel_drop_right']}")
        print(f"  Bump Sensors       : Left={drops['bump_left']}, Right={drops['bump_right']}")

        cliffs = telemetry.get("cliffs", {})
        print(f"  Cliff Sensors      : L={cliffs.get('cliff_left')}, FL={cliffs.get('cliff_front_left')}, FR={cliffs.get('cliff_front_right')}, R={cliffs.get('cliff_right')}")
        print("=" * 60)
        print("\n[SUCCESS] Roomba 960 is fully responsive to Open Interface commands!\n")

    except Exception as e:
        print(f"\n[!] Connection Verification Failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await client.disconnect()


def main():
    parser = argparse.ArgumentParser(description="Verify Roomba serial connection and read telemetry.")
    parser.add_argument("--port", type=str, default=None, help="Serial port (e.g. COM11 or /dev/ttyACM0). Auto-detected if omitted.")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    args = parser.parse_args()

    asyncio.run(run_verification(port=args.port, baudrate=args.baud))


if __name__ == "__main__":
    main()
