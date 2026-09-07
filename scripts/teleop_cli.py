"""
Interactive Keyboard WASD Teleoperation CLI for Roomba 960.
Cross-platform support for Windows (msvcrt) and Linux/Raspberry Pi (termios/tty).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from roomba.driver.client import RoombaClient
from roomba.driver.discovery import find_roomba_port

# Windows console encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def get_key_nonblocking() -> Optional[str]:
    """Read a single key non-blockingly from stdin across Windows and Linux."""
    if sys.platform == "win32":
        import msvcrt
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            if ch in (b"\x00", b"\xe0"):
                msvcrt.getch()
                return None
            try:
                return ch.decode("utf-8", errors="ignore")
            except Exception:
                return None
        return None
    else:
        import select
        r, _, _ = select.select([sys.stdin], [], [], 0)
        if r:
            return sys.stdin.read(1)
        return None


def print_ui(speed: int, mode: str, status: str = "IDLE"):
    print(f"\r  [Status: {status:<15}]  Speed: {speed:>3} mm/s  |  Mode: {mode:<4}   ", end="", flush=True)


async def run_teleop(
    port: Optional[str] = None,
    initial_speed: int = 150,
    mode: str = "safe",
    deadman_timeout: float = 0.45,
):
    print("=" * 65)
    print("           Roomba 960 WASD Teleoperation Console")
    print("=" * 65)
    print("  Controls:")
    print("    [W]        : Forward")
    print("    [S]        : Backward")
    print("    [A]        : Spin Left (CCW)")
    print("    [D]        : Spin Right (CW)")
    print("    [Space]    : Stop Immediately")
    print("    [+] / [-]  : Speed Up / Speed Down (+/- 25 mm/s)")
    print("    [Q] / [Esc]: Quit cleanly")
    print("-" * 65)

    target_port = port or find_roomba_port()
    if not target_port:
        print("[!] Error: Roomba serial port not found.")
        sys.exit(1)

    print(f"Connecting to Roomba on {target_port}...")
    client = RoombaClient(port=target_port, baudrate=115200)

    try:
        await client.connect()
        print(f"[OK] Connected to {target_port}.")

        if mode.lower() == "full":
            await client.full_mode()
        else:
            await client.safe_mode()

        await asyncio.sleep(0.1)

        try:
            telemetry = await client.get_telemetry()
            print(f"[OK] Telemetry: Battery {telemetry['voltage_v']}V ({telemetry['battery_percent']}%)")
        except Exception as e:
            print(f"[!] Warning: Could not read telemetry: {e}")

        print("\nReady! Press WASD keys to drive. Hold key down for continuous drive.")
        print("-" * 65)

        current_speed = initial_speed
        last_key_time = 0.0
        is_driving = False
        last_action = "STOPPED"

        print_ui(current_speed, mode.upper(), last_action)

        while True:
            key = get_key_nonblocking()
            now = time.monotonic()

            if key is not None:
                key_lower = key.lower()

                if key_lower in ("q", "\x1b"):
                    print("\n\n[Exiting] Stopping motors and disconnecting...")
                    break

                elif key_lower in ("w", "'"):
                    await client.drive_direct(current_speed, current_speed)
                    last_action = "FORWARD"
                    last_key_time = now
                    is_driving = True

                elif key_lower in ("s", "ד"):
                    await client.drive_direct(-current_speed, -current_speed)
                    last_action = "BACKWARD"
                    last_key_time = now
                    is_driving = True

                elif key_lower in ("a", "ש"):
                    # Turn Left: right wheel positive, left wheel negative
                    await client.drive_direct(current_speed, -current_speed)
                    last_action = "TURN LEFT"
                    last_key_time = now
                    is_driving = True

                elif key_lower in ("d", "ג"):
                    # Turn Right: right wheel negative, left wheel positive
                    await client.drive_direct(-current_speed, current_speed)
                    last_action = "TURN RIGHT"
                    last_key_time = now
                    is_driving = True

                elif key == " ":
                    await client.stop()
                    last_action = "STOPPED"
                    is_driving = False

                elif key in ("+", "="):
                    current_speed = min(500, current_speed + 25)

                elif key in ("-", "_"):
                    current_speed = max(25, current_speed - 25)

                print_ui(current_speed, mode.upper(), last_action)

            # Dead-man's switch
            if is_driving and (now - last_key_time > deadman_timeout):
                await client.stop()
                is_driving = False
                last_action = "STOPPED (IDLE)"
                print_ui(current_speed, mode.upper(), last_action)

            await asyncio.sleep(0.03)

    except KeyboardInterrupt:
        print("\n\nInterrupted by user (Ctrl+C).")
    finally:
        try:
            await client.stop()
        except Exception:
            pass
        await client.disconnect()
        print("\nDisconnected cleanly.\n")


def main():
    parser = argparse.ArgumentParser(description="WASD keyboard teleoperation for Roomba 960.")
    parser.add_argument("--port", type=str, default=None, help="COM / tty port. Auto-detected if omitted.")
    parser.add_argument("--speed", type=int, default=150, help="Drive speed in mm/s (default: 150)")
    parser.add_argument("--mode", choices=["safe", "full"], default="safe", help="OI mode: safe or full")
    parser.add_argument("--timeout", type=float, default=0.45, help="Dead-man switch timeout in seconds")
    args = parser.parse_args()

    asyncio.run(
        run_teleop(
            port=args.port,
            initial_speed=args.speed,
            mode=args.mode,
            deadman_timeout=args.timeout,
        )
    )


if __name__ == "__main__":
    main()
