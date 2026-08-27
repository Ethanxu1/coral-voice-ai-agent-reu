"""Regression tests: follow/capture must respect the sim/hardware toggle.

follow_start and capture_pose dispatch continuously to the robot through
FollowController, which previously ignored the caller's sim_only choice
entirely (dispatch_servo_commands defaulted to hardware whenever the server
ran in robot mode). try_handle_system_intent must forward whatever sim_only
the caller passed in, same as /move and the chat motion planner, so a session
in the sim-only toggle state never streams commands to the physical robot via
these paths either.
"""

import pytest

import server


class _FakeFollowController:
    def __init__(self):
        self.is_following = False
        self.start_follow_calls: list[bool | None] = []
        self.capture_calls: list[bool | None] = []

    async def start_follow(self, status_fn, sim_only=None):
        self.start_follow_calls.append(sim_only)

    async def stop_follow(self, status_fn=None):
        pass

    async def trigger_capture_and_mimic(self, status_fn, sim_only=None):
        self.capture_calls.append(sim_only)


class _FakeWebSocket:
    async def send_json(self, payload):
        pass


@pytest.fixture(autouse=True)
def _fake_follow_controller(monkeypatch):
    fake = _FakeFollowController()
    monkeypatch.setattr(server, "follow_controller", fake)
    yield fake


@pytest.mark.anyio
async def test_follow_start_forwards_sim_only(_fake_follow_controller):
    dialog = server.SavePoseDialog()
    handled = await server.try_handle_system_intent(
        "follow me", _FakeWebSocket(), dialog, sim_only=True
    )
    assert handled is True
    assert _fake_follow_controller.start_follow_calls == [True]


@pytest.mark.anyio
async def test_capture_pose_forwards_sim_only(_fake_follow_controller):
    dialog = server.SavePoseDialog()
    handled = await server.try_handle_system_intent(
        "take a picture", _FakeWebSocket(), dialog, sim_only=False
    )
    assert handled is True
    assert _fake_follow_controller.capture_calls == [False]


@pytest.fixture
def anyio_backend():
    return "asyncio"
