"""
Roomba Autonomous Operating Modes and Behavioral Scripts.
Provides pluggable operating modes (manual, wander, follow_person).
"""

from roomba.modes.base import BaseMode, BaseBehavior, RobotContext
from roomba.modes.manager import ModeManager, BehaviorManager
from roomba.modes.manual import ManualMode, ManualTeleopBehavior
from roomba.modes.wander import WanderMode, WanderBehavior
from roomba.modes.follow_person import FollowPersonMode, FollowPersonBehavior

__all__ = [
    "BaseMode",
    "BaseBehavior",
    "RobotContext",
    "ModeManager",
    "BehaviorManager",
    "ManualMode",
    "ManualTeleopBehavior",
    "WanderMode",
    "WanderBehavior",
    "FollowPersonMode",
    "FollowPersonBehavior",
]
