"""
Unified Command-Line Interface for the Roomba 960 Controller.

Usage:
  python -m roomba [web] [--port 8000] [--mock] [--mode safe]
  python -m roomba teleop [--speed 150] [--mode safe]
  python -m roomba monitor [--rate 5] [--once]
  python -m roomba verify [--port COM11]
  python -m roomba test-wheel [--speed 100] [--duration 1.0] [--mode full]
"""

from __future__ import annotations

import sys
import argparse


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="roomba",
        description="Roomba 960 Autonomous Controller & Web Hub",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # 1. Web server (default if no subcommand given)
    web_parser = subparsers.add_parser("web", help="Launch the Web Control Cockpit")
    web_parser.add_argument("--host", type=str, default="0.0.0.0", help="Host address (default: 0.0.0.0)")
    web_parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    web_parser.add_argument("--mock", action="store_true", help="Launch in offline mock simulation")
    web_parser.add_argument("--serial-port", type=str, default=None, help="Serial port (auto-detected if omitted)")
    web_parser.add_argument("--mode", type=str, choices=["safe", "full"], default="safe", help="Default mode")
    web_parser.add_argument("--auto-connect", action="store_true", help="Auto-connect on startup")

    # 2. Teleop CLI
    teleop_parser = subparsers.add_parser("teleop", help="Interactive terminal WASD keyboard teleop")
    teleop_parser.add_argument("--port", type=str, default=None, help="Serial port")
    teleop_parser.add_argument("--baud", type=int, default=115200, help="Baud rate")
    teleop_parser.add_argument("--speed", type=int, default=150, help="Initial speed in mm/s")
    teleop_parser.add_argument("--mode", type=str, choices=["safe", "full"], default="safe", help="Roomba mode")
    teleop_parser.add_argument("--timeout", type=float, default=0.45, help="Deadman timeout in seconds")

    # 3. Monitor
    monitor_parser = subparsers.add_parser("monitor", help="Live hardware sensor monitor dashboard")
    monitor_parser.add_argument("--port", type=str, default=None, help="Serial port")
    monitor_parser.add_argument("--baud", type=int, default=115200, help="Baud rate")
    monitor_parser.add_argument("--rate", type=float, default=5.0, help="Sampling frequency in Hz")
    monitor_parser.add_argument("--once", action="store_true", help="Print single snapshot and exit")

    # 4. Verify
    verify_parser = subparsers.add_parser("verify", help="Hardware connection and telemetry diagnostics")
    verify_parser.add_argument("--port", type=str, default=None, help="Target serial port")
    verify_parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")

    # 5. Test Wheel
    wheel_parser = subparsers.add_parser("test-wheel", help="Gentle test of right drive wheel")
    wheel_parser.add_argument("--port", type=str, default=None, help="Serial port")
    wheel_parser.add_argument("--speed", type=int, default=100, help="Speed in mm/s (default: 100)")
    wheel_parser.add_argument("--duration", type=float, default=1.0, help="Duration in seconds (default: 1.0)")
    wheel_parser.add_argument("--mode", type=str, choices=["safe", "full"], default="safe", help="Mode")

    # Allow running web server as default if first arg looks like an option or empty
    argv = sys.argv[1:]
    known_commands = {"web", "teleop", "monitor", "verify", "test-wheel", "-h", "--help"}
    if not argv or (argv[0] not in known_commands and not argv[0].startswith("-h")):
        argv = ["web"] + argv

    args = parser.parse_args(argv)

    if args.command == "web":
        from scripts.run_server import run_web_server
        run_web_server(
            host=args.host,
            port=args.port,
            serial_port=args.serial_port,
            mock=args.mock,
            mode=args.mode,
            auto_connect=args.auto_connect,
        )

    elif args.command == "teleop":
        from scripts.teleop import run_teleop
        import asyncio
        asyncio.run(
            run_teleop(
                port=args.port,
                baudrate=args.baud,
                speed=args.speed,
                mode=args.mode,
                timeout=args.timeout,
            )
        )

    elif args.command == "monitor":
        from scripts.monitor import run_monitor
        import asyncio
        asyncio.run(
            run_monitor(
                port=args.port,
                baudrate=args.baud,
                rate_hz=args.rate,
                once=args.once,
            )
        )

    elif args.command == "verify":
        from scripts.verify import run_verification
        import asyncio
        asyncio.run(
            run_verification(
                port=args.port,
                baudrate=args.baud,
            )
        )

    elif args.command == "test-wheel":
        from scripts.test_wheel import run_wheel_test
        import asyncio
        asyncio.run(
            run_wheel_test(
                port=args.port,
                speed=args.speed,
                duration=args.duration,
                mode=args.mode,
            )
        )

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
