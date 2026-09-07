"""
Roomba Driver Subpackage.
Contains protocol definitions, serial communication client, mock simulator, and port discovery.
"""

from .protocol import (
    RoombaOpcode,
    RoombaSensorPacket,
    RoombaSensors,
    OI_MODES,
    CHARGING_STATES,
    PRESET_TUNES,
    rtttl_to_notes,
    text_to_morse_notes,
)
from .discovery import find_roomba_port, list_serial_ports
from .client import RoombaClient
from .mock import MockRoombaClient

__all__ = [
    "RoombaOpcode",
    "RoombaSensorPacket",
    "RoombaSensors",
    "OI_MODES",
    "CHARGING_STATES",
    "PRESET_TUNES",
    "rtttl_to_notes",
    "text_to_morse_notes",
    "find_roomba_port",
    "list_serial_ports",
    "RoombaClient",
    "MockRoombaClient",
]
