"""
Unit tests for autonomous behavior plugins and BehaviorManager.
"""

import pytest
import pytest_asyncio
from roomba.core.controller import RobotController
from roomba.behaviors.base import RobotContext
from roomba.behaviors.wander import WanderBehavior
from roomba.behaviors.person_follower import FollowPersonBehavior


@pytest_asyncio.fixture
async def controller():
    c = RobotController()
    await c.connect(mock=True)
    yield c
    await c.disconnect()


@pytest.mark.asyncio
async def test_behavior_manager_registry(controller):
    """Verify behavior registration and listing."""
    bm = controller.behavior_manager
    behaviors = bm.list_behaviors()
    names = [b["name"] for b in behaviors]

    assert "manual" in names
    assert "wander" in names
    assert "follow_person" in names
    assert bm.active_name == "manual"


@pytest.mark.asyncio
async def test_behavior_switching_and_estop(controller):
    """Verify switching to an autonomous behavior and stopping via E-STOP."""
    bm = controller.behavior_manager

    # Switch to wander
    await bm.set_active("wander")
    assert bm.active_name == "wander"

    # Trigger E-STOP
    await controller.emergency_stop()
    assert controller.armed is False
    assert bm.active_name == "manual"


@pytest.mark.asyncio
async def test_wander_behavior_obstacle_reaction(controller):
    """Verify WanderBehavior backs up when an obstacle is detected."""
    wander = WanderBehavior(cruise_speed=150)
    ctx_clear = RobotContext(
        controller=controller,
        telemetry={"bumps_and_drops": {"bump_left": False, "bump_right": False}},
    )

    cmd_clear = await wander.update(ctx_clear)
    assert cmd_clear.left == 150
    assert cmd_clear.right == 150

    # Simulate bumper collision
    ctx_bumped = RobotContext(
        controller=controller,
        telemetry={"bumps_and_drops": {"bump_left": True, "bump_right": False}},
    )
    cmd_bump = await wander.update(ctx_bumped)
    assert cmd_bump.left < 0
    assert cmd_bump.right < 0  # Reversing!


@pytest.mark.asyncio
async def test_follow_person_behavior_steering(controller):
    """Verify FollowPersonBehavior steers toward detected person."""
    follower = FollowPersonBehavior(forward_speed=150)

    # 1. Target centered: should drive forward
    ctx_center = RobotContext(
        controller=controller,
        telemetry={"bumps_and_drops": {"bump_left": False, "bump_right": False}},
        perception={"target_person": {"x_center": 0.5, "bbox_width": 0.2, "confidence": 0.9}},
    )
    cmd_center = await follower.update(ctx_center)
    assert cmd_center.left > 0
    assert cmd_center.right > 0
    assert abs(cmd_center.left - cmd_center.right) <= 5

    # 2. Target to the right (x_center = 0.8): left wheel faster than right wheel
    ctx_right = RobotContext(
        controller=controller,
        telemetry={"bumps_and_drops": {"bump_left": False, "bump_right": False}},
        perception={"target_person": {"x_center": 0.8, "bbox_width": 0.2, "confidence": 0.9}},
    )
    cmd_right = await follower.update(ctx_right)
    assert cmd_right.left > cmd_right.right  # Steering right!

    # 3. Target to the left (x_center = 0.2): right wheel faster than left wheel
    ctx_left = RobotContext(
        controller=controller,
        telemetry={"bumps_and_drops": {"bump_left": False, "bump_right": False}},
        perception={"target_person": {"x_center": 0.2, "bbox_width": 0.2, "confidence": 0.9}},
    )
    cmd_left = await follower.update(ctx_left)
    assert cmd_left.right > cmd_left.left  # Steering left!
