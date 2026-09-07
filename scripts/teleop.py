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
    baudrate: int = 115200,
    speed: int = 150,
    initial_speed: Optional[int] = None,
    mode: str = "safe",
    timeout: float = 0.45,
    deadman_timeout: Optional[float] = None,
):
    actual_speed = initial_speed if initial_speed is not None else speed
    actual_timeout = deadman_timeout if deadman_timeout is not None else timeout

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

    print(f"Connecting to {target_port} at {baudrate} baud...")
    client = RoombaClient(port=target_port, baudrate=baudrate)

    # Linux terminal raw mode setup
    old_term_settings = None
    if sys.platform != "win32":
        import termios
        import tty
        old_term_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())

    try:
        await client.connect()
        if mode.lower() == "full":
            await client.full_mode()
            print("[OK] Roomba entered FULL MODE.")
        else:
            await client.safe_mode()
            print("[OK] Roomba entered SAFE MODE.")

        print("[OK] Teleop active. Press WASD to drive!\n")

        current_speed = actual_speed
        last_key_time = 0.0
        is_driving = False

        while True:
            key = get_key_nonblocking()
            now = time.monotonic()

            if key:
                key_lower = key.lower()
                if key_lower in ("q", "\x1b"):  # Q or Escape
                    print("\nQuitting teleoperation...")
                    break

                elif key == " ":
                    await client.stop()
                    is_driving = False
                    print_ui(current_speed, mode, "EMERGENCY STOP")

                elif key in ("+", "="):
                    current_speed = min(500, current_speed + 25)
                    print_ui(current_speed, mode, "SPEED UP")

                elif key in ("-", "_"):
                    current_speed = max(25, current_speed - 25)
                    print_ui(current_speed, mode, "SPEED DOWN")

                elif key_lower == "w":
                    await client.drive_direct(current_speed, current_speed)
                    last_key_time = now
                    is_driving = True
                    print_ui(current_speed, mode, "FORWARD")

                elif key_lower == "s":
                    await client.drive_direct(-current_speed, -current_speed)
                    last_key_time = now
                    is_driving = True
                    print_ui(current_speed, mode, "BACKWARD")

                elif key_lower == "a":
                    await client.drive_direct(-current_speed, current_speed)
                    last_key_time = now
                    is_driving = True
                    print_ui(current_speed, mode, "SPIN LEFT")

                elif key_lower == "d":
                    await client.drive_direct(current_speed, -current_speed)
                    last_key_time = now
                    is_driving = True
                    print_ui(current_speed, mode, "SPIN RIGHT")

            # Deadman safety cutoff
            if is_driving and (now - last_key_time > actual_timeout):
                await client.stop()
                is_driving = False
                print_ui(current_speed, mode, "IDLE (Halted)")

            await asyncio.sleep(0.02)

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    finally:
        if sys.platform != "win32" and old_term_settings:
            import termios
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_term_settings)

        print("\nStopping Roomba motors and disconnecting...")
        try:
            await client.stop()
            await client.disconnect()
        except Exception:
            pass
        print("[OK] Safe shutdown complete.")


def main():
    parser = argparse.ArgumentParser(description="Roomba 960 Keyboard WASD Teleop")
    parser.add_argument("--port", type=str, default=None, help="Serial port (auto-detected if omitted)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--speed", type=int, default=150, help="Drive speed in mm/s (default: 150)")
    parser.add_argument(
        "--mode",
        type=str,
        choices=["safe", "full"],
        default="safe",
        help="Roomba mode: safe (default) or full",
    )
    parser.add_argument("--timeout", type=float, default=0.45, help="Dead-man switch timeout in seconds")
    args = parser.parse_args()

    asyncio.run(
        run_teleop(
            port=args.port,
            baudrate=args.baud,
            speed=args.speed,
            mode=args.mode,
            timeout=args.timeout,
        )
    )


if __name__ == "__main__":
    main()
