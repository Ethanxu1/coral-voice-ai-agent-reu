"""Regression tests for _execute_on_hardware_if_connected().

Saving a pose (voice save-dialog, POST /poses/save-current) and demonstrating
a saved pose (POST /poses/play, the "execute_saved_pose" chat action, the
end-of-session replay) must always reach hardware once the backend is
connected to it, regardless of the composing-only sim/hardware toggle — see
the 2026-08-27 fix ("live mode isn't executing anything on the robot
anymore"). This exercises the shared helper both endpoints call after saving.
"""

import asyncio

import pytest

import server

JOINTS = {"head_pan": 0.3}


class _FakeSim:
    def __init__(self, joints: dict[str, float]):
        self._joints = dict(joints)

    def get_all_joint_states(self):
        return dict(self._joints)

    def send_commands(self, commands):
        pass


class _RecordingHardware:
    def __init__(self):
        self.sent: list[list] = []

    def send_commands(self, commands):
        self.sent.append(list(commands))


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(server, "simulator", _FakeSim(JOINTS))
    monkeypatch.setattr(server, "sim_dispatcher", _FakeSim(JOINTS))
    monkeypatch.setattr(server, "hardware_in_sync", False)
    yield


def test_executes_on_hardware_when_connected(monkeypatch):
    hardware = _RecordingHardware()
    monkeypatch.setattr(server, "robot_mode", "robot")
    monkeypatch.setattr(server, "hardware_dispatcher", hardware)

    asyncio.run(server._execute_on_hardware_if_connected(JOINTS))

    assert len(hardware.sent) == 1
    assert hardware.sent[0], "expected at least one servo command dispatched"


def test_noop_in_sim_mode(monkeypatch):
    hardware = _RecordingHardware()
    monkeypatch.setattr(server, "robot_mode", "sim")
    monkeypatch.setattr(server, "hardware_dispatcher", hardware)

    asyncio.run(server._execute_on_hardware_if_connected(JOINTS))

    assert hardware.sent == []


def test_hardware_error_does_not_raise(monkeypatch):
    class _BrokenHardware:
        def send_commands(self, commands):
            raise ConnectionError("robot unreachable")

    monkeypatch.setattr(server, "robot_mode", "robot")
    monkeypatch.setattr(server, "hardware_dispatcher", _BrokenHardware())

    # Should not raise — a hardware hiccup shouldn't fail the save/demonstrate
    # action that already completed on the frontend's terms.
    asyncio.run(server._execute_on_hardware_if_connected(JOINTS))
