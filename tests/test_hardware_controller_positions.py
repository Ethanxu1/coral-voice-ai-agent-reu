"""Regression test: AiNexHardwareController.get_joint_positions() must raise,
not silently degrade, when the robot agent has no /positions route.

robot_server.py (the Pi side, src/robot/pi/nodes/server.py) only implements
/health and /move — /positions was never built there, so every real call
404s. get_joint_positions() used to swallow that into dict(STAND_PULSE), a
joint-name-keyed dict pretending to be the servo-ID-keyed shape a real
/positions response actually has. get_joint_states() parses keys with
int(sid_str), so every one of those fake entries silently failed to parse
and got dropped -- returning {} that read as a legitimate (if empty)
hardware reading instead of "hardware state unknown".

Callers already have a try/except specifically to fall back to the
simulator on failure (_get_robot_state(), _sync_sim_to_hardware() in
server.py) -- the fallback just never raised, so it never engaged. That's
how a saved pose ended up with 0 joints: _get_robot_state() confidently
returned {} from "hardware" instead of falling back to the simulator's
real, current state. See the 2026-08-29 fix.
"""

import httpx
import pytest

from robot.hardware_controller import AiNexHardwareController


def _controller_with_fake_client(handler) -> AiNexHardwareController:
    """Build a controller without the real network call __init__ makes."""
    controller = AiNexHardwareController.__new__(AiNexHardwareController)
    controller._base = "http://robot.test:9000"
    controller._client = httpx.Client(transport=httpx.MockTransport(handler))
    return controller


def test_get_joint_positions_raises_when_positions_route_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    controller = _controller_with_fake_client(handler)
    with pytest.raises(httpx.HTTPStatusError):
        controller.get_joint_positions()


def test_get_joint_states_raises_when_positions_route_missing():
    """The failure must propagate all the way up so _get_robot_state()'s
    try/except actually catches something and falls back to the simulator."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    controller = _controller_with_fake_client(handler)
    with pytest.raises(httpx.HTTPStatusError):
        controller.get_joint_states()


def test_get_joint_positions_returns_real_data_when_available():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"positions": {"23": 452, "24": 500}})

    controller = _controller_with_fake_client(handler)
    assert controller.get_joint_positions() == {"23": 452, "24": 500}


def test_get_joint_states_converts_servo_ids_to_joint_names():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"positions": {"23": 500, "24": 500}})

    controller = _controller_with_fake_client(handler)
    states = controller.get_joint_states()
    assert set(states.keys()) == {"head_pan", "head_tilt"}
