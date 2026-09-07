"""
Testing script to move the Roomba's right wheel gently.
Connects to Roomba 960 over micro-USB, verifies communication,
and commands only the right wheel to rotate forward at a controlled
speed for a brief duration before safely stopping.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from roomba.driver.client import RoombaClient
from roomba.driver.discovery import find_roomba_port

# Ensure UTF-8 stdout on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


async def run_wheel_test(
    port: Optional[str] = None,
    speed: int = 100,
    duration: float = 1.0,
    mode: str = "safe",
) -> None:
    print("=" * 60)
    print("              Roomba Right Wheel Motion Test")
    print("=" * 60)

    target_port = port or find_roomba_port()
    if not target_port:
        print("[!] Error: No Roomba port found.")
        sys.exit(1)

    print(f"Connecting to {target_port}...")
    client = RoombaClient(port=target_port, baudrate=115200)

    try:
        await client.connect()
        print(f"[OK] Connected to {target_port}.")

        if mode.lower() == "full":
            print("Activating FULL MODE (Opcode 132)...")
            await client.full_mode()
        else:
            print("Activating SAFE MODE (Opcode 131)...")
            await client.safe_mode()

        await asyncio.sleep(0.1)

        # Pre-flight check: query battery and wheel drops
        telemetry = await client.get_telemetry()
        print(f"[OK] Roomba responsive. Battery: {telemetry['voltage_v']}V ({telemetry['battery_percent']}%)")

        drops = telemetry["bumps_and_drops"]
        if drops["wheel_drop_right"] or drops["wheel_drop_left"]:
            print("\n[!] Warning: Wheel drop sensor is currently ACTIVE (robot appears elevated).")
            if mode.lower() == "safe":
                print("  In SAFE mode, the Roomba's safety system stops motors if wheels are dropped.")
                print("  If you are testing on a workbench with wheels suspended, run with: --mode full\n")

        print(f"\n--> Commanding RIGHT wheel at {speed} mm/s for {duration:.1f}s (Left wheel = 0 mm/s)...")
        await client.move_wheel(
            right_speed_mm_s=speed,
            left_speed_mm_s=0,
            duration_s=duration,
        )
        print("[OK] Motion completed and wheel motor halted successfully.")

    except KeyboardInterrupt:
        print("\nInterrupted by user! Halting motors immediately...")
        try:
            await client.stop()
        except Exception:
            pass
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.disconnect()
        print("Disconnected cleanly.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Move Roomba right wheel for testing.")
    parser.add_argument("--port", type=str, default=None, help="COM port (e.g. COM11). Auto-detected if omitted.")
    parser.add_argument("--speed", type=int, default=100, help="Right wheel velocity in mm/s (-500 to 500, default: 100)")
    parser.add_argument("--duration", type=float, default=1.0, help="Duration in seconds (default: 1.0)")
    parser.add_argument(
        "--mode",
        choices=["safe", "full"],
        default="safe",
        help="OI Mode: 'safe' (default, safety sensors stop motors) or 'full' (for workbench tests with wheels elevated)",
    )
    args = parser.parse_args()

    asyncio.run(
        run_wheel_test(
            port=args.port,
            speed=args.speed,
            duration=args.duration,
            mode=args.mode,
        )
    )


if __name__ == "__main__":
    main()
