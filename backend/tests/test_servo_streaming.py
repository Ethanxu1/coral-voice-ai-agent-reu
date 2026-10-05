"""Streaming servo commands to the real robot without waiting.

Measured on the robot, 2026-10-02: every /move blocks until the motion ends
(body.py sleeps duration + 0.1 s), ~0.3 s straight to the Pi and ~0.5 s via
the app. Follow mode sends a 45 ms move ~20 times a second, so on hardware
it ran at ~2-3 updates a second as move-stop jolts, and a second move during
one was refused ("robot busy"). /stream hands targets to the servos and
returns at once; the servos glide there over the given time themselves.
"""

from __future__ import annotations

import importlib
import json
import sys
import threading
import types
from pathlib import Path

import httpx
import pytest

from app.robot.interface import ServoCommand

NODES = Path(__file__).resolve().parents[1] / "app" / "robot" / "pi" / "nodes"


# ── Pi side: server.py /stream ───────────────────────────────────────────────


@pytest.fixture
def pi_server(monkeypatch):
    monkeypatch.syspath_prepend(str(NODES))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    published: list[str] = []
    monkeypatch.setattr(server, "_stream_pub", types.SimpleNamespace(publish=published.append))
    from fastapi.testclient import TestClient

    yield server, TestClient(server.app), published
    sys.modules.pop("server", None)


def test_stream_publishes_clamped_targets_and_returns_at_once(pi_server):
    server, client, published = pi_server
    r = client.post("/stream", json=[
        {"servo_id": 1, "position": 999, "duration_ms": 50},   # l_ank_roll, limit 600
        {"servo_id": 9, "position": 480, "duration_ms": 50},
        {"servo_id": 23, "position": 500, "duration_ms": 50},  # head: dropped
    ])
    assert r.status_code == 200 and r.json()["status"] == "sent"
    frames = json.loads(published[0])
    assert frames == [[{"l_ank_roll": 600, "l_hip_roll": 480}, 50]]


def test_stream_keeps_short_move_times(pi_server):
    """/move floors every move at 100 ms; a 45 ms follow tick must stay 45 ms
    or each tick lasts twice as long as the gap between ticks."""
    server, client, published = pi_server
    client.post("/stream", json=[{"servo_id": 9, "position": 480, "duration_ms": 45}])
    assert json.loads(published[0])[0][1] == 45


def test_stream_steps_aside_while_a_blocking_move_plays(pi_server):
    server, client, published = pi_server
    with server._move_lock:
        r = client.post("/stream", json=[{"servo_id": 9, "position": 480, "duration_ms": 50}])
    assert r.status_code == 429
    assert published == []


def test_stream_reports_when_ros_is_not_up(pi_server, monkeypatch):
    server, client, _ = pi_server
    monkeypatch.setattr(server, "_stream_pub", None)
    r = client.post("/stream", json=[{"servo_id": 9, "position": 480, "duration_ms": 50}])
    assert r.status_code == 503


# ── Pi side: body.py plays a stream frame without sleeping ───────────────────


@pytest.fixture
def body_module(monkeypatch):
    """Import body.py with stand-ins for ROS and the AiNex SDK."""
    calls: list[tuple[int, list]] = []

    class FakeMotionManager:
        def set_servos_position(self, duration, servos):
            calls.append((duration, servos))

    fakes = {
        "rospy": types.SimpleNamespace(
            init_node=lambda *a, **k: None, Service=lambda *a, **k: None,
            Subscriber=lambda *a, **k: None, loginfo=lambda *a, **k: None,
            logwarn=lambda *a, **k: None, spin=lambda: None),
        "std_msgs": types.ModuleType("std_msgs"),
        "std_msgs.msg": types.SimpleNamespace(Bool=object, String=object),
        "std_srvs": types.ModuleType("std_srvs"),
        "std_srvs.srv": types.SimpleNamespace(Trigger=object, TriggerResponse=object),
        "ainex_kinematics": types.ModuleType("ainex_kinematics"),
        "ainex_kinematics.motion_manager": types.SimpleNamespace(MotionManager=FakeMotionManager),
        "ainex_demo": types.ModuleType("ainex_demo"),
        "ainex_demo.srv": types.SimpleNamespace(BodyCommand=object, BodyCommandResponse=object),
    }
    for name, mod in fakes.items():
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.syspath_prepend(str(NODES))
    sys.modules.pop("body", None)
    body = importlib.import_module("body")
    node = body.BodyNode()
    calls.clear()  # drop the stand pose sent at start-up
    yield body, node, calls
    sys.modules.pop("body", None)


def test_body_plays_a_stream_frame_immediately(body_module, monkeypatch):
    body, node, calls = body_module
    slept: list[float] = []
    monkeypatch.setattr(body.time, "sleep", slept.append)
    msg = types.SimpleNamespace(data=json.dumps([[{"l_hip_roll": 480, "r_hip_roll": 520}, 45]]))
    node._handle_stream(msg)
    assert calls == [(45, [[9, 480], [10, 520]])]
    assert slept == [], "a stream frame must not wait for the motion to finish"


def test_body_ignores_a_malformed_stream_frame(body_module):
    body, node, calls = body_module
    node._handle_stream(types.SimpleNamespace(data="not json"))
    assert calls == []


# ── Mac side: hardware controller ────────────────────────────────────────────


def _controller(monkeypatch, handler):
    import app.robot.hardware_controller as hc

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(hc.httpx, "Client", lambda **kw: real_client(transport=transport, **kw))
    return hc.AiNexHardwareController(robot_ip="robot", port=9000)


CMDS = [ServoCommand(servo_id=9, position=480, duration_ms=45)]


def test_stream_commands_post_to_stream(monkeypatch):
    seen: list[tuple[str, object]] = []

    def handler(req):
        seen.append((req.url.path, json.loads(req.content) if req.content else None))
        return httpx.Response(200, json={"status": "sent"})

    ctl = _controller(monkeypatch, handler)
    ctl.stream_commands(CMDS)
    assert ctl.flush_stream(2.0)
    path, body = seen[-1]
    assert path == "/stream"
    assert body[0]["servo_id"] == 9


def test_stream_falls_back_to_move_on_a_robot_without_stream(monkeypatch):
    """Old Pi code has no /stream: keep working, blocking, and stop asking."""
    paths: list[str] = []

    def handler(req):
        paths.append(req.url.path)
        if req.url.path == "/stream":
            return httpx.Response(404)
        return httpx.Response(200, json={"status": "done"})

    ctl = _controller(monkeypatch, handler)
    ctl.stream_commands(CMDS)
    assert ctl.flush_stream(2.0)
    ctl.stream_commands(CMDS)
    assert ctl.flush_stream(2.0)
    assert paths.count("/stream") == 1
    assert paths.count("/move") == 2


def test_stream_drops_a_frame_while_the_robot_is_busy(monkeypatch):
    """Latest wins: the next tick carries a newer target anyway."""
    ctl = _controller(monkeypatch, lambda req: httpx.Response(429))
    ctl.stream_commands(CMDS)  # no exception
    assert ctl.flush_stream(2.0)


def test_stream_commands_never_wait_for_the_network(monkeypatch):
    """Measured 2026-10-02 over Wi-Fi: /stream round trip median 93 ms, worst
    765 ms. Follow mode waited for it, so the robot got ~10 updates/s and
    every slow trip was a visible jerk. Sending happens in the background."""
    import threading as th
    import time

    release = th.Event()

    def handler(req):
        if req.url.path == "/stream":
            release.wait(2.0)
        return httpx.Response(200, json={"status": "sent"})

    ctl = _controller(monkeypatch, handler)
    t0 = time.perf_counter()
    ctl.stream_commands(CMDS)
    assert time.perf_counter() - t0 < 0.05
    release.set()
    assert ctl.flush_stream(2.0)


def test_only_the_newest_target_is_sent_after_a_slow_trip(monkeypatch):
    import threading as th

    release = th.Event()
    sent: list[int] = []

    def handler(req):
        if req.url.path == "/stream":
            sent.append(json.loads(req.content)[0]["position"])
            if len(sent) == 1:
                release.wait(2.0)
        return httpx.Response(200, json={"status": "sent"})

    ctl = _controller(monkeypatch, handler)
    for pos in (400, 450, 480):
        ctl.stream_commands([ServoCommand(servo_id=9, position=pos, duration_ms=45)])
        if pos == 400:
            import time
            time.sleep(0.1)  # first one is on the wire and stuck
    release.set()
    assert ctl.flush_stream(2.0)
    import app.robot.hardware_controller as hc
    hw = [hc.sim_units_to_hardware_units(p, "l_hip_roll") for p in (400, 480)]
    assert sent == hw, "the stale middle target must be skipped"


def test_each_streamed_move_lasts_until_the_next_one_arrives(monkeypatch):
    """A 45 ms move sent every ~100 ms leaves the servos idle half the time:
    move-stop jolts. The move time follows the real gap between sends."""
    import time

    durations: list[int] = []

    def handler(req):
        if req.url.path == "/stream":
            durations.append(json.loads(req.content)[0]["duration_ms"])
        return httpx.Response(200, json={"status": "sent"})

    ctl = _controller(monkeypatch, handler)
    for _ in range(3):
        ctl.stream_commands(CMDS)
        assert ctl.flush_stream(2.0)
        time.sleep(0.12)
    assert all(d >= 120 for d in durations[1:]), durations
    assert all(d <= 200 for d in durations), durations


def test_a_blocking_move_cancels_stream_targets_not_yet_sent(monkeypatch):
    """Stop following, then move to stand: a follow target still waiting in
    the sender must not reach the robot after the stand move."""
    import threading as th
    import time

    release = th.Event()
    order: list[str] = []

    def handler(req):
        order.append(req.url.path)
        if req.url.path == "/stream" and order.count("/stream") == 1:
            release.wait(2.0)
        return httpx.Response(200, json={"status": "done"})

    ctl = _controller(monkeypatch, handler)
    ctl.stream_commands(CMDS)          # on the wire, stuck
    time.sleep(0.1)
    ctl.stream_commands(CMDS)          # waiting in the sender
    th.Timer(0.2, release.set).start()
    ctl.send_commands(CMDS)            # e.g. back to stand
    assert ctl.flush_stream(2.0)
    assert order[-1] == "/move", order
    assert order.count("/stream") == 1, order


# ── Mac side: dispatch and follow wiring ─────────────────────────────────────


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _FakeHardware:
    def __init__(self):
        self.sent, self.streamed = [], []

    def send_commands(self, commands):
        self.sent.append(commands)

    def stream_commands(self, commands):
        self.streamed.append(commands)


@pytest.mark.anyio
@pytest.mark.parametrize("stream", [False, True])
async def test_dispatch_streams_only_when_asked(monkeypatch, stream):
    from app.services import motion
    from app.state import state

    hw = _FakeHardware()
    monkeypatch.setattr(state, "sim_dispatcher", None)
    monkeypatch.setattr(state, "hardware_dispatcher", hw)
    monkeypatch.setattr(state, "robot_mode", "robot")
    await motion.dispatch_servo_commands(CMDS, sim_only=None, stream=stream)
    assert (hw.streamed, hw.sent) == (([CMDS], []) if stream else ([], [CMDS]))


def test_follow_uses_the_stream_path_for_live_ticks():
    from app.follow_controller import FollowController
    from app.main import app as _app  # noqa: F401  (main wires the real controller)
    from app.services.motion import stream_servo_commands
    from app.state import state

    async def dispatch(commands, sim_only=None):
        pass

    async def stream(commands, sim_only=None):
        pass

    assert FollowController(dispatch, stream_fn=stream)._live_dispatch is stream
    assert FollowController(dispatch)._live_dispatch is dispatch
    assert stream_servo_commands is not None and state is not None
