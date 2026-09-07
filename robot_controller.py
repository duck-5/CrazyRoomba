"""
Backward-compatibility shim for robot_controller.py.
Delegates to roomba.core.controller.
"""

from roomba.core.controller import RobotController

__all__ = ["RobotController"]
