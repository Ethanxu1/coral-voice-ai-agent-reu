"""Marching on the real robot with Hiwonder's own walking engine.

Confirmed on the robot 2026-10-05 (coral_walk_test.py): the engine marches
in place, steps forward and back, and turns. Follow mode starts it when the
person marches. The Pi side (nodes/walking.py, server.py /walk) owns the
legs while it walks, and stops on its own when the laptop goes quiet, so a
dropped Wi-Fi link can't leave the robot marching off the table.
"""

from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path

import httpx
import pytest

NODES = Path(__file__).resolve().parents[1] / "app" / "robot" / "pi" / "nodes"


# ── Pi side: Walker ──────────────────────────────────────────────────────────


class FakeEngine:
    def __init__(self):
        self.commands: list[str] = []
        self.published: list[types.SimpleNamespace] = []

    def get_params(self):
        return types.SimpleNamespace(
            period_time=400, dsp_ratio=0.2, y_swap_amplitude=0.02, x_move_amplitude=0.0,
            y_move_amplitude=0.0, z_move_amplitude=0.02, angle_move_amplitude=0.0,
            arm_swing_gain=0.5, period_times=0,
        )

    def set_params(self, msg):
        self.published.append(types.SimpleNamespace(**vars(msg)))

    def command(self, name):
        self.commands.append(name)


@pytest.fixture
def walking(monkeypatch):
    monkeypatch.syspath_prepend(str(NODES))
    sys.modules.pop("walking", None)
    mod = importlib.import_module("walking")
    yield mod
    sys.modules.pop("walking", None)


def _walker(walking, now):
    engine, stands = FakeEngine(), []
    w = walking.Walker(engine, stand_legs=lambda: stands.append(True),
                       clock=lambda: now[0], sleep=lambda s: None, spawn=lambda f: f())
    return w, engine, stands


def test_walk_starts_the_engine_once_with_clamped_safe_settings(walking):
    w, engine, _ = _walker(walking, [0.0])
    got = w.walk(forward=0.5, turn=-30, step_height=0.2)
    w.walk(forward=0.0, turn=0, step_height=0.02)
    assert engine.commands == ["start"]
    first = engine.published[0]
    assert first.x_move_amplitude == walking.FORWARD_MAX_M
    assert first.angle_move_amplitude == -walking.TURN_MAX_DEG
    assert first.z_move_amplitude == walking.STEP_HEIGHT_M[1]
    assert first.arm_swing_gain == 0 and first.period_times == 0
    assert got == {"forward": walking.FORWARD_MAX_M, "turn": -walking.TURN_MAX_DEG,
                   "step_height": walking.STEP_HEIGHT_M[1]}
    assert engine.published[1].x_move_amplitude == 0.0
    assert w.legs_busy


def test_walk_stops_and_stands_when_the_laptop_goes_quiet(walking):
    now = [0.0]
    w, engine, stands = _walker(walking, now)
    w.walk()
    now[0] = walking.KEEPALIVE_TIMEOUT_S - 0.1
    assert not w.check_timeout()
    w.walk()
    now[0] += walking.KEEPALIVE_TIMEOUT_S + 0.1
    assert w.check_timeout()
    assert engine.commands == ["start", "stop"]
    assert stands == [True]
    assert not w.legs_busy


def test_stop_finishes_the_step_then_stands(walking):
    w, engine, stands = _walker(walking, [0.0])
    w.stop()
    assert engine.commands == [] and stands == []  # nothing to stop
    w.walk()
    w.stop()
    assert engine.commands == ["start", "stop"] and stands == [True]
    assert not w.legs_busy


def test_walk_is_refused_while_the_legs_are_settling(walking):
    w, engine, _ = _walker(walking, [0.0])
    pending = []
    w._spawn = pending.append  # settle not finished yet
    w.walk()
    w.stop()
    assert w.legs_busy
    with pytest.raises(walking.WalkerBusy):
        w.walk()
    pending[0]()
    assert not w.legs_busy
    w.walk()
    assert engine.commands == ["start", "stop", "start"]


# ── Pi side: server.py /walk ─────────────────────────────────────────────────


@pytest.fixture
def pi_server(monkeypatch, walking):
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    published: list[str] = []
    monkeypatch.setattr(server, "_stream_pub", types.SimpleNamespace(publish=published.append))
    w, engine, stands = _walker(walking, [0.0])
    monkeypatch.setattr(server, "_walker", w)
    from fastapi.testclient import TestClient

    yield server, TestClient(server.app), published, engine
    sys.modules.pop("server", None)


def test_walk_endpoint_starts_and_stops(pi_server):
    server, client, _, engine = pi_server
    r = client.post("/walk", json={"forward": 0.01, "turn": 5})
    assert r.status_code == 200 and r.json()["walking"] is True
    assert client.get("/walk/status").json()["state"] == "walking"
    assert client.post("/walk/stop").json() == {"walking": False}
    assert engine.commands == ["start", "stop"]


def test_walk_endpoint_reports_when_the_engine_is_missing(pi_server, monkeypatch):
    server, client, _, _ = pi_server
    monkeypatch.setattr(server, "_walker", None)
    assert client.post("/walk", json={}).status_code == 503


def test_stream_leaves_the_legs_to_the_walk(pi_server):
    """Follow keeps streaming the arms while the robot marches; leg targets
    in the same frames must not fight the walking engine."""
    server, client, published, _ = pi_server
    client.post("/walk", json={})
    client.post("/stream", json=[
        {"servo_id": 9, "position": 480, "duration_ms": 50},    # l_hip_roll: leg
        {"servo_id": 13, "position": 700, "duration_ms": 50},   # l_sho_pitch: arm
    ])
    assert json.loads(published[-1]) == [[{"l_sho_pitch": 700}, 50]]


def test_move_stops_the_walk_before_playing(pi_server, monkeypatch):
    server, client, _, engine = pi_server
    played = []
    monkeypatch.setattr(server, "_call_body_service", lambda seq, *a: played.append(seq) or 0)
    client.post("/walk", json={})
    r = client.post("/move", json=[{"servo_id": 9, "position": 480, "duration_ms": 300}])
    assert r.status_code == 200
    assert engine.commands == ["start", "stop"] and played


# ── Mac side: AiNexHardwareController.walk ───────────────────────────────────


def _controller(monkeypatch, handler):
    import app.robot.hardware_controller as hc

    real_client = httpx.Client
    monkeypatch.setattr(hc.httpx, "Client",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    return hc.AiNexHardwareController(robot_ip="robot", port=9000)


def test_controller_walk_posts_to_walk_and_stop(monkeypatch):
    seen = []

    def handler(req):
        seen.append((req.url.path, req.content and json.loads(req.content)))
        return httpx.Response(200, json={})

    ctl = _controller(monkeypatch, handler)
    ctl.walk(True)
    ctl.walk(False)
    assert seen[-2] == ("/walk", {"forward": 0.0, "turn": 0.0})
    assert seen[-1][0] == "/walk/stop"


def test_controller_walk_tolerates_a_robot_still_settling(monkeypatch):
    def handler(req):
        if req.url.path == "/walk":
            return httpx.Response(409)
        return httpx.Response(200, json={"status": "ok"})

    _controller(monkeypatch, handler).walk(True)  # no raise: the next keepalive retries


def test_follow_turn_reaches_the_robot_as_turn_not_forward(monkeypatch):
    import asyncio

    from app.services import motion
    from app.state import state

    seen = []
    monkeypatch.setattr(state, "robot_mode", "robot")
    monkeypatch.setattr(state, "hardware_dispatcher", types.SimpleNamespace(
        walk=lambda walking, forward=0.0, turn=0.0: seen.append((walking, forward, turn))))
    asyncio.run(motion.set_robot_walking(True, 8.0))
    asyncio.run(motion.set_robot_walking(False))
    assert seen == [(True, 0.0, 8.0), (False, 0.0, 0.0)]


def test_sim_mode_never_calls_the_robot_walk(monkeypatch):
    import asyncio

    from app.services import motion
    from app.state import state

    monkeypatch.setattr(state, "robot_mode", "sim")
    monkeypatch.setattr(state, "hardware_dispatcher", None)
    asyncio.run(motion.set_robot_walking(True))
    assert state.hardware_dispatcher is None
