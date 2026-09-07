"""
Global configuration for the Roomba Controller.
Supports environment variable overrides and cross-platform detection.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from dataclasses import dataclass

# Base Directories
BASE_DIR = Path(__file__).resolve().parent.parent
PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "web" / "static"
if not STATIC_DIR.exists():
    STATIC_DIR = BASE_DIR / "static"
DEPLOY_DIR = BASE_DIR / "deploy"


def is_raspberry_pi() -> bool:
    """Detect if running on a Raspberry Pi."""
    if sys.platform != "linux":
        return False
    try:
        model_path = Path("/proc/device-tree/model")
        if model_path.exists():
            model = model_path.read_text().lower()
            return "raspberry pi" in model
    except Exception:
        pass
    return False


@dataclass
class RoombaConfig:
    # Serial Connection
    baudrate: int = int(os.getenv("ROOMBA_BAUDRATE", "115200"))
    serial_port: str | None = os.getenv("ROOMBA_PORT", None)
    serial_timeout: float = float(os.getenv("ROOMBA_SERIAL_TIMEOUT", "2.0"))

    # Operating Mode & Safety
    default_mode: str = os.getenv("ROOMBA_MODE", "Safe")  # "Safe" or "Full"
    deadman_timeout: float = float(os.getenv("ROOMBA_DEADMAN_TIMEOUT", "0.5"))
    telemetry_rate_hz: float = float(os.getenv("ROOMBA_TELEMETRY_RATE_HZ", "7.0"))
    behavior_rate_hz: float = float(os.getenv("ROOMBA_BEHAVIOR_RATE_HZ", "10.0"))

    # Web Server
    http_host: str = os.getenv("ROOMBA_HOST", "0.0.0.0")
    http_port: int = int(os.getenv("ROOMBA_HTTP_PORT", "8000"))

    # Simulation / Mock Mode
    mock_mode: bool = os.getenv("ROOMBA_MOCK", "false").lower() in ("true", "1", "yes")

    # Camera / Perception
    camera_enabled: bool = os.getenv("ROOMBA_CAMERA_ENABLED", "false").lower() in ("true", "1", "yes")
    camera_device_index: int = int(os.getenv("ROOMBA_CAMERA_INDEX", "0"))

    @property
    def telemetry_interval(self) -> float:
        return 1.0 / max(1.0, self.telemetry_rate_hz)

    @property
    def behavior_interval(self) -> float:
        return 1.0 / max(1.0, self.behavior_rate_hz)


config = RoombaConfig()
