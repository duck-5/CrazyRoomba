"""
Backward-compatibility shim for roomba_client.py.
Delegates to the modular roomba.driver subpackage.
"""

from roomba.driver.protocol import (
    RoombaOpcode,
    RoombaSensorPacket,
    RoombaSensors,
    CHARGING_STATES,
    OI_MODES,
    PACKET_100_STRUCT_FMT,
    PRESET_TUNES,
    rtttl_to_notes,
    text_to_morse_notes,
)
from roomba.driver.discovery import find_roomba_port, list_serial_ports
from roomba.driver.client import RoombaClient

__all__ = [
    "RoombaOpcode",
    "RoombaSensorPacket",
    "RoombaSensors",
    "CHARGING_STATES",
    "OI_MODES",
    "PACKET_100_STRUCT_FMT",
    "PRESET_TUNES",
    "rtttl_to_notes",
    "text_to_morse_notes",
    "find_roomba_port",
    "list_serial_ports",
    "RoombaClient",
]
