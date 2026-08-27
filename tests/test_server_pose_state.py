"""Regression tests for _get_robot_state()'s hardware-vs-simulator source pick.

Poses are always composed live in the simulator (dispatch_servo_commands always
sends to sim_dispatcher); the physical robot only receives a move when the
caller explicitly opts in (sim_only=False). Reading "current pose" for a save
must reflect whichever one the last dispatch actually reached, not just
whether the server happens to be running in hardware mode.
"""

import asyncio

import pytest

import server
from robot.interface import ServoCommand

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
def _hardware_mode_with_diverged_state(monkeypatch):
    monkeypatch.setattr(server, "robot_mode", "robot")
    monkeypatch.setattr(server, "simulator", _FakeController(SIM_JOINTS))
    monkeypatch.setattr(server, "sim_dispatcher", _FakeController(SIM_JOINTS))
    monkeypatch.setattr(server, "hardware_dispatcher", _FakeController(HW_JOINTS))
    monkeypatch.setattr(server, "hardware_in_sync", False)
    yield


def test_state_reads_simulator_before_any_hardware_dispatch():
    # Nothing has been sent to hardware yet (fresh session, or every move so far
    # was sim_only) — the simulator is the only thing that reflects what's
    # actually been composed, so it must be what gets reported/saved.
    assert server._get_robot_state() == SIM_JOINTS


def test_state_still_reads_simulator_after_a_sim_only_dispatch():
    commands = [ServoCommand(servo_id=1, position=500, duration_ms=100)]
    asyncio.run(server.dispatch_servo_commands(commands, sim_only=True))
    assert server._get_robot_state() == SIM_JOINTS


def test_state_reads_hardware_after_an_explicit_hardware_dispatch():
    commands = [ServoCommand(servo_id=1, position=500, duration_ms=100)]
    asyncio.run(server.dispatch_servo_commands(commands, sim_only=False))
    assert server._get_robot_state() == HW_JOINTS
