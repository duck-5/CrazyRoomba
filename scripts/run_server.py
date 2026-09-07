"""
Main launcher script for Roomba Web Control Cockpit.
Usage:
  python scripts/run_server.py [--port 8000] [--mock] [--mode safe]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure root directory is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import uvicorn
from roomba.web.app import app, controller
from roomba.config import config


def run_web_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    serial_port: str | None = None,
    mock: bool = False,
    mode: str = "safe",
    auto_connect: bool = False,
) -> None:
    """Run the Roomba web hub."""
    controller.default_mode = mode

    if mock:
        asyncio.run(controller.connect(mock=True))
    elif auto_connect:
        try:
            asyncio.run(controller.connect(port=serial_port, mock=False))
        except Exception as e:
            print(f"[!] Warning: Auto-connect failed: {e}")
            print("   You can connect anytime via the Web Cockpit.")

    print("=" * 65)
    print("      ROOMBA 960 MODULAR CONTROLLER & COCKPIT")
    print("=" * 65)
    print(f"  * Web Dashboard URL : http://localhost:{port}")
    print(f"  * Platform          : {sys.platform}")
    print(f"  * Initial Mode      : {controller.default_mode.upper()}")
    print(f"  * Mock Simulator    : {'ENABLED' if mock else 'DISABLED'}")
    print("=" * 65)

    uvicorn.run(app, host=host, port=port, log_level="info")


def main() -> None:
    parser = argparse.ArgumentParser(description="Roomba 960 Web Control Server")
    parser.add_argument("--host", type=str, default=config.http_host, help="Host address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=config.http_port, help="HTTP Port (default: 8000)")
    parser.add_argument("--serial-port", type=str, default=config.serial_port, help="COM / tty port. Auto-detected if omitted.")
    parser.add_argument("--mock", action="store_true", default=config.mock_mode, help="Run in mock simulation mode without hardware.")
    parser.add_argument(
        "--mode",
        type=str,
        choices=["safe", "full"],
        default=config.default_mode,
        help="Initial Roomba mode (default: safe)",
    )
    parser.add_argument("--auto-connect", action="store_true", help="Connect immediately on startup.")
    args = parser.parse_args()

    run_web_server(
        host=args.host,
        port=args.port,
        serial_port=args.serial_port,
        mock=args.mock,
        mode=args.mode,
        auto_connect=args.auto_connect,
    )


if __name__ == "__main__":
    main()
