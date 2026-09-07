"""
Backward-compatibility alias module for roomba.modes.
All autonomous operating modes and behavior scripts reside in roomba.modes.
"""

from roomba.modes import (
    BaseMode,
    BaseBehavior,
    RobotContext,
    ModeManager,
    BehaviorManager,
    ManualMode,
    ManualTeleopBehavior,
    WanderMode,
    WanderBehavior,
    FollowPersonMode,
    FollowPersonBehavior,
)

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
