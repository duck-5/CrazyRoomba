"""
Cross-platform serial port discovery for Roomba 960 (Windows & Linux / Raspberry Pi).
Detects iRobot Corporation Vendor ID 0x27A6 across COM ports and /dev/tty devices.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any
import serial.tools.list_ports

logger = logging.getLogger("roomba.driver.discovery")

IROBOT_VID = 0x27A6
IROBOT_PID = 0x0002


def is_irobot_device(port_info) -> bool:
    """Check if a serial port corresponds to an iRobot device."""
    if port_info.vid == IROBOT_VID:
        return True
    hwid = (port_info.hwid or "").lower()
    desc = (port_info.description or "").lower()
    if "27a6" in hwid or "irobot" in desc or "roomba" in desc:
        return True
    return False


def list_serial_ports() -> List[Dict[str, Any]]:
    """
    List all detected serial ports with metadata and iRobot matching.
    Works seamlessly on Windows, Linux, and Raspberry Pi.
    """
    ports = []
    for p in serial.tools.list_ports.comports():
        is_roomba = is_irobot_device(p)
        vid_str = f"0x{p.vid:04X}" if p.vid else None
        pid_str = f"0x{p.pid:04X}" if p.pid else None

        ports.append({
            "device": p.device,
            "description": p.description,
            "vid": vid_str,
            "pid": pid_str,
            "is_roomba": is_roomba,
            "platform": sys.platform,
        })
    return ports


def find_roomba_port() -> Optional[str]:
    """
    Search connected serial ports for an iRobot Roomba device.
    Matches by Vendor ID 0x27A6 or descriptions.
    Supports Linux /dev/ttyACM*, /dev/ttyUSB*, and Windows COM*.
    """
    ports = list(serial.tools.list_ports.comports())

    # 1. Match by known iRobot Vendor ID
    for p in ports:
        if p.vid == IROBOT_VID:
            logger.info(f"Found iRobot device on {p.device} (VID: 0x{p.vid:04X}, PID: 0x{p.pid:04X})")
            return p.device

    # 2. Check description / HWID keywords
    for p in ports:
        if is_irobot_device(p):
            logger.info(f"Found Roomba candidate by HWID/description on {p.device}: {p.description}")
            return p.device

    # 3. Linux / Raspberry Pi: Check /dev/serial/by-id symlinks
    if sys.platform.startswith("linux"):
        by_id_dir = Path("/dev/serial/by-id")
        if by_id_dir.exists():
            for link in by_id_dir.iterdir():
                link_name = link.name.lower()
                if "irobot" in link_name or "roomba" in link_name or "27a6" in link_name:
                    target = str(link.resolve())
                    logger.info(f"Found Roomba by udev id link: {link} -> {target}")
                    return target

        # Linux common default ports for CDC ACM
        for dev in ("/dev/ttyACM0", "/dev/ttyUSB0", "/dev/ttyACM1"):
            if Path(dev).exists():
                logger.info(f"Fallback to existing Linux serial device: {dev}")
                return dev

    # 4. Windows common default ports (e.g. COM11)
    if sys.platform == "win32":
        for p in ports:
            if p.device.upper() == "COM11":
                return p.device

    # 5. Fallback: First USB serial port
    for p in ports:
        desc = (p.description or "").lower()
        if "usb" in desc or "cdc" in desc or "acm" in desc:
            logger.info(f"Falling back to first available USB serial port: {p.device} ({p.description})")
            return p.device

    return None
