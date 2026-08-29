"""Regression tests for _get_robot_state()'s hardware-vs-simulator source pick.

Poses are always composed live in the simulator (dispatch_servo_commands always
sends to sim_dispatcher); the physical robot only receives a move when the
caller explicitly opts in (sim_only=False). Reading "current pose" for a save
must reflect whichever one the last dispatch actually reached, not just
whether the server happens to be running in hardware mode.
"""

import asyncio

import pytest

from app.robot.interface import ServoCommand
from app.services.motion import _get_robot_state, dispatch_servo_commands
from app.state import state

SIM_JOINTS = {"head_pan": 0.1}
HW_JOINTS = {"head_pan": 0.9}  # stale physical position, left over from a prior session


class _FakeController:
    def __init__(self, joints: dict[str, float]):
        self._joints = dict(joints)

    def get_all_joint_states(self):
        return dict(self._joints)

    def get_joint_states(self):
        return dict(self._joints)

    def send_commands(self, commands):
        pass


@pytest.fixture(autouse=True)
def _hardware_mode_with_diverged_state():
    state.robot_mode = "robot"
    state.simulator = _FakeController(SIM_JOINTS)
    state.sim_dispatcher = _FakeController(SIM_JOINTS)
    state.hardware_dispatcher = _FakeController(HW_JOINTS)
    state.hardware_in_sync = False
    yield
    state.robot_mode = "sim"
    state.simulator = None
    state.sim_dispatcher = None
    state.hardware_dispatcher = None
    state.hardware_in_sync = False


def test_state_reads_simulator_before_any_hardware_dispatch():
    # Nothing has been sent to hardware yet (fresh session, or every move so far
    # was sim_only) — the simulator is the only thing that reflects what's
    # actually been composed, so it must be what gets reported/saved.
    assert _get_robot_state() == SIM_JOINTS


def test_state_still_reads_simulator_after_a_sim_only_dispatch():
    commands = [ServoCommand(servo_id=1, position=500, duration_ms=100)]
    asyncio.run(dispatch_servo_commands(commands, sim_only=True))
    assert _get_robot_state() == SIM_JOINTS


def test_state_reads_hardware_after_an_explicit_hardware_dispatch():
    commands = [ServoCommand(servo_id=1, position=500, duration_ms=100)]
    asyncio.run(dispatch_servo_commands(commands, sim_only=False))
    assert _get_robot_state() == HW_JOINTS
