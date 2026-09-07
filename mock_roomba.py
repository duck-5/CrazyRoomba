"""
Backward-compatibility shim for mock_roomba.py.
Delegates to roomba.driver.mock.
"""

from roomba.driver.mock import MockRoombaClient

__all__ = ["MockRoombaClient"]
