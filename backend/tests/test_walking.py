"""Marching on the real robot with Hiwonder's own walking engine.

Confirmed on the robot 2026-10-05 (coral_walk_test.py): the engine marches
in place (and can turn). Follow mode starts it when the person marches. The Pi
side (nodes/walking.py, server.py /walk) owns the legs while it walks,
never steps forward/back/sideways (the robot often stands on a desk), and
stops on its own when the laptop goes quiet or after MAX_WALK_S.
"""

from __future__ import annotations

import importlib
import json
import math
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
            period_time=400, dsp_ratio=0.2, y_swap_amplitude=0.02, x_move_amplitude=0.01,
            y_move_amplitude=0.01, z_move_amplitude=0.02, angle_move_amplitude=0.0,
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


def _walker(walking, now, pending=None):
    engine, stands = FakeEngine(), []
    spawn = (lambda f: f()) if pending is None else pending.append
    w = walking.Walker(engine, stand_legs=lambda: stands.append(True),
                       clock=lambda: now[0], sleep=lambda s: None, spawn=spawn)
    return w, engine, stands


def test_walk_marches_in_place_with_safe_settings_and_never_turns(walking):
    """2026-10-13: the user wants marching in place only -- no turning to
    either side. Only the gyro heading hold (zero here: no gyro) may set it."""
    w, engine, _ = _walker(walking, [0.0])
    got = w.walk(step_height=0.2)
    w.walk()
    assert engine.commands == ["start"]
    first = engine.published[0]
    # Never steps off the desk: only the small creep correction, if any.
    assert first.x_move_amplitude == walking.X_TRIM_M
    assert abs(walking.X_TRIM_M) <= walking.MAX_TRIM_M
    assert first.y_move_amplitude == 0
    assert first.angle_move_amplitude == 0
    assert first.z_move_amplitude == walking.STEP_HEIGHT_M[1]
    assert first.arm_swing_gain == pytest.approx(math.radians(walking.ARM_SWING_DEG))
    assert first.period_times == 0
    assert got == {"step_height": walking.STEP_HEIGHT_M[1], "x_trim_m": walking.X_TRIM_M}
    assert engine.published[1].angle_move_amplitude == 0
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
    assert engine.commands == ["start", "stop"] and stands == [True]
    assert not w.legs_busy


def test_a_march_is_capped_and_needs_a_stop_before_marching_again(walking):
    now = [0.0]
    w, engine, _ = _walker(walking, now)
    w.walk()
    while now[0] < walking.MAX_WALK_S + 1:
        now[0] += 1.0
        try:
            w.walk()
        except walking.WalkerBusy:
            break
        w.check_timeout()
    assert engine.commands == ["start", "stop"]
    with pytest.raises(walking.WalkerBusy):
        w.walk()                       # keepalives alone don't restart it
    w.stop()                           # the laptop's stop clears the cap
    w.walk()
    assert engine.commands == ["start", "stop", "start"]


def test_stop_finishes_the_step_then_stands(walking):
    w, engine, stands = _walker(walking, [0.0])
    w.stop()
    assert engine.commands == [] and stands == []
    w.walk()
    w.stop()
    assert engine.commands == ["start", "stop"] and stands == [True]
    assert not w.legs_busy


def test_walk_is_refused_while_the_legs_are_settling(walking):
    pending = []
    w, engine, _ = _walker(walking, [0.0], pending)
    w.walk()
    w.stop()
    assert w.legs_busy
    with pytest.raises(walking.WalkerBusy):
        w.walk()
    pending[0]()
    assert not w.legs_busy
    w.walk()
    assert engine.commands == ["start", "stop", "start"]


# ── Pi side: server.py ───────────────────────────────────────────────────────


@pytest.fixture
def pi_server(monkeypatch, walking):
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    played: list = []
    monkeypatch.setattr(server, "_call_body_service", lambda seq, *a: played.append(seq) or 0)
    w, engine, _ = _walker(walking, [0.0])
    monkeypatch.setattr(server, "_walker", w)
    from fastapi.testclient import TestClient

    yield server, TestClient(server.app), played, engine
    sys.modules.pop("server", None)


def test_walk_endpoint_starts_and_stops(pi_server):
    server, client, _, engine = pi_server
    r = client.post("/walk", json={})
    assert r.status_code == 200 and r.json()["walking"] is True
    assert client.get("/walk/status").json()["state"] == "walking"
    assert client.post("/walk/stop").json() == {"walking": False}
    assert engine.commands == ["start", "stop"]


def test_walk_endpoint_has_no_way_to_step_forward(pi_server):
    server, client, _, engine = pi_server
    client.post("/walk", json={"forward": 0.02, "turn": 8})
    assert engine.published[-1].x_move_amplitude == server_trim(server)
    assert engine.published[-1].angle_move_amplitude == 0      # no way to turn either


def server_trim(server):
    import walking as w

    return w.X_TRIM_M


def test_walk_endpoint_reports_when_the_engine_is_missing(pi_server, monkeypatch):
    server, client, _, _ = pi_server
    monkeypatch.setattr(server, "_walker", None)
    assert client.post("/walk", json={}).status_code == 503


def test_walk_is_not_held_up_by_a_move_in_progress(pi_server):
    """Follow mode sends a blocking /move several times a second; a walk
    renewal must not be refused while one plays."""
    server, client, _, _ = pi_server
    with server._move_lock:
        assert client.post("/walk", json={}).status_code == 200


def test_move_leaves_legs_and_arms_to_the_march(pi_server):
    """The walking engine swings the arms in time with the steps, so follow
    mode's arm targets must not fight it either; the march keeps going."""
    server, client, played, engine = pi_server
    client.post("/walk", json={})
    r = client.post("/move", json=[
        {"servo_id": 9, "position": 480, "duration_ms": 100},    # l_hip_roll: leg
        {"servo_id": 13, "position": 700, "duration_ms": 100},   # l_sho_pitch: arm
    ])
    assert r.status_code == 200
    assert played == []
    assert engine.commands == ["start"]                         # still walking


def test_move_plays_normally_when_not_marching(pi_server):
    server, client, played, _ = pi_server
    client.post("/move", json=[{"servo_id": 13, "position": 700, "duration_ms": 100}])
    assert played == [[({"l_sho_pitch": 700}, 100)]]


def test_move_with_only_legs_while_walking_plays_nothing(pi_server):
    server, client, played, _ = pi_server
    client.post("/walk", json={})
    r = client.post("/move", json=[{"servo_id": 9, "position": 480, "duration_ms": 100}])
    assert r.status_code == 200 and played == []


# ── Mac side: AiNexHardwareController.walk ───────────────────────────────────


def _controller(monkeypatch, handler):
    import app.robot.hardware_controller as hc

    real_client = httpx.Client
    monkeypatch.setattr(hc.httpx, "Client",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    return hc.AiNexHardwareController(robot_ip="robot", port=9000)


def test_controller_walk_posts_walk_and_stop(monkeypatch):
    seen = []

    def handler(req):
        seen.append((req.url.path, req.content and json.loads(req.content)))
        return httpx.Response(200, json={})

    ctl = _controller(monkeypatch, handler)
    ctl.walk(True)
    ctl.walk(False)
    assert seen[-2] == ("/walk", {})
    assert seen[-1][0] == "/walk/stop"


def test_controller_walk_tolerates_a_busy_walker(monkeypatch):
    def handler(req):
        if req.url.path == "/walk":
            return httpx.Response(409)
        return httpx.Response(200, json={"status": "ok"})

    _controller(monkeypatch, handler).walk(True)  # no raise: the next renewal retries


def test_set_robot_walking_starts_and_stops_the_robot(monkeypatch):
    import asyncio

    from app.services import motion
    from app.state import state

    seen = []
    monkeypatch.setattr(state, "hardware_dispatcher", types.SimpleNamespace(
        walk=lambda walking: seen.append(walking)))
    asyncio.run(motion.set_robot_walking(True))
    asyncio.run(motion.set_robot_walking(False))
    assert seen == [True, False]



def test_marches_are_capped_at_20_seconds_to_limit_creep(walking):
    """2026-10-12: marching 'in place' crept slightly forward on a table
    (feet slip; the engine doesn't sense where they land)."""
    assert walking.MAX_WALK_S == 20.0
    import app.follow_marching as fm

    assert fm.MAX_MARCH_S == 20.0


def test_drift_trim_is_applied_and_can_never_become_walking(walking, monkeypatch):
    monkeypatch.setattr(walking, "X_TRIM_M", -0.003)
    w, engine, _ = _walker(walking, [0.0])
    w.walk()
    assert engine.published[-1].x_move_amplitude == pytest.approx(-0.003)
    monkeypatch.setattr(walking, "X_TRIM_M", 0.5)        # a bad setting
    w.walk()
    assert abs(engine.published[-1].x_move_amplitude) <= walking.MAX_TRIM_M == 0.005
    assert engine.published[-1].y_move_amplitude == 0



# ── Heading hold from the gyro (2026-10-12) ──────────────────────────────────
# Marching in place, the robot turned ~30-45 deg to its right in 16 s, with
# or without arm swing (coral_walk_test.py, arms still, did the same): its
# own drift, which also changes with surface and battery. So it measures its
# turning and steers against it.


def _held_walker(walking, now, rate):
    engine, stands = FakeEngine(), []
    w = walking.Walker(engine, stand_legs=lambda: stands.append(True),
                       clock=lambda: now[0], sleep=lambda s: None, spawn=lambda f: f(),
                       yaw_rate=lambda: rate[0])
    return w, engine


def _run(w, now, seconds, dt=0.02):
    for _ in range(int(seconds / dt)):
        now[0] += dt
        w.sense()


def test_heading_hold_steers_back_against_drift_to_the_right(walking):
    now, rate = [0.0], [0.0]
    w, engine = _held_walker(walking, now, rate)
    w.walk()
    rate[0] = -3.0                      # turning to the robot's right
    _run(w, now, 2.0)
    assert w.yaw_deg == pytest.approx(-6.0, abs=0.2)
    w.walk()
    assert engine.published[-1].angle_move_amplitude > 0     # steer left


def test_gyro_bias_is_learned_while_standing(walking):
    now, rate = [0.0], [0.8]            # a gyro that reads 0.8 deg/s at rest
    w, engine = _held_walker(walking, now, rate)
    _run(w, now, 10.0)
    w.walk()
    _run(w, now, 5.0)                   # marching straight, same bias
    assert abs(w.yaw_deg) < 1.0
    w.walk()
    assert abs(engine.published[-1].angle_move_amplitude) < 0.5


def test_hold_correction_is_bounded(walking):
    now, rate = [0.0], [0.0]
    w, engine = _held_walker(walking, now, rate)
    w.walk()
    rate[0] = -50.0
    _run(w, now, 3.0)
    w.walk()
    assert engine.published[-1].angle_move_amplitude <= walking.HOLD_MAX_DEG


def test_without_a_gyro_there_is_no_hold(walking):
    w, engine, _ = _walker(walking, [0.0])
    w.walk()
    w.sense()
    w.walk()
    assert engine.published[-1].angle_move_amplitude == 0


def test_yaw_rate_comes_from_the_configured_gyro_axis(walking):
    values = [0.0, 1.0, 0.0, 11.0, 22.0, 33.0, 0.0, 0.0, 0.0]   # accel, gyro, mag
    expected = walking.YAW_GYRO_SIGN * values[3 + walking.YAW_GYRO_AXIS]
    assert walking.yaw_rate_from_imu(values) == expected
    assert walking.yaw_rate_from_imu(None) is None


def test_imu_endpoint_returns_raw_values(pi_server, monkeypatch):
    server, client, _, _ = pi_server
    monkeypatch.setattr(server, "_board", types.SimpleNamespace(latest=lambda: [0.0, 1.0, 0.0, 1, 2, 3, 4, 5, 6]))
    assert client.get("/imu").json() == {"values": [0.0, 1.0, 0.0, 1, 2, 3, 4, 5, 6]}
    monkeypatch.setattr(server, "_board", None)
    assert client.get("/imu").status_code == 503


def test_walk_status_reports_the_heading(pi_server):
    server, client, _, _ = pi_server
    client.post("/walk", json={})
    assert client.get("/walk/status").json()["yaw_deg"] == 0.0


def test_latest_imu_keeps_the_last_reading_for_every_consumer(walking):
    """Board().get_imu() hands each reading out once (it reads a queue,
    None when empty): with the heading hold polling at 50 Hz, /imu only
    ever got None (seen live 2026-10-12). One reader keeps the latest."""
    queue = [None, [0, 1, 0, 1, 2, 3, 0, 0, 0], None, None]
    now = [0.0]
    imu = walking.LatestImu(lambda: queue.pop(0) if queue else None, clock=lambda: now[0])
    for _ in range(4):
        imu.poll_once()
    assert imu.latest() == [0, 1, 0, 1, 2, 3, 0, 0, 0]
    assert imu.latest() == [0, 1, 0, 1, 2, 3, 0, 0, 0]       # not used up
    now[0] += walking.IMU_STALE_S + 0.1
    assert imu.latest() is None                              # too old to trust


def test_gyro_bias_ignores_motion_while_standing(walking):
    """In follow mode the arms move before a march starts and twist the body;
    those readings must not be taken as the gyro's resting offset."""
    now, rate = [0.0], [0.8]
    w, engine = _held_walker(walking, now, rate)
    for i in range(500):                     # 10 s standing, arms moving
        rate[0] = 0.8 + (25.0 if (i // 10) % 2 == 0 else -15.0)
        now[0] += 0.02
        w.sense()
    rate[0] = 0.8
    _run(w, now, 5.0)                        # a few seconds actually still
    w.walk()
    _run(w, now, 5.0)
    assert abs(w.yaw_deg) < 1.0



# ── 2026-10-13 live: slow right turn over several marches; slow stop ────────


def _turning_robot(walking, now, drift):
    """A robot whose real turning rate = its own drift + what it is told
    (deg/step x calibration / step period)."""
    engine = FakeEngine()
    state = {"cmd": 0.0}
    orig = engine.set_params

    def set_params(msg):
        state["cmd"] = msg.angle_move_amplitude
        orig(msg)

    engine.set_params = set_params
    w = walking.Walker(engine, stand_legs=lambda: None, clock=lambda: now[0],
                       sleep=lambda s: None, spawn=lambda f: f(),
                       yaw_rate=lambda: (drift + state["cmd"] * 1.125 / 0.5) if w.state == "walking" else 0.0)
    return w, engine


def _march(w, now, seconds, dt=0.02, renew=0.3):
    next_renew = 0.0
    for _ in range(int(seconds / dt)):
        now[0] += dt
        if now[0] >= next_renew:
            w.walk()
            next_renew = now[0] + renew
        w.sense()


def test_a_long_march_holds_its_heading_without_a_steady_offset(walking):
    now = [0.0]
    w, _ = _turning_robot(walking, now, drift=-2.4)        # ~1.2 deg/step right
    for _ in range(100):
        now[0] += 0.02
        w.sense()                                           # standing still first
    _march(w, now, 18.0)
    assert abs(w.yaw_deg) < 1.5


def test_the_heading_is_kept_across_marches(walking):
    """Stopping and starting again must not make 'wherever it faces now'
    the new straight ahead, or small turns add up march after march."""
    now = [0.0]
    w, engine = _held_walker(walking, now, [0.0])
    w.walk()
    w._lock.acquire(); w.yaw_deg = -10.0; w._lock.release()   # it ended 10 deg right
    w.stop()
    now[0] += 3.0
    w.walk()                                                  # marching again soon after
    assert engine.published[-1].angle_move_amplitude > 0      # steers back left


def test_the_heading_reference_resets_after_a_long_pause(walking):
    now = [0.0]
    w, engine = _held_walker(walking, now, [0.0])
    w.walk()
    w._lock.acquire(); w.yaw_deg = -10.0; w._lock.release()
    w.stop()
    now[0] += walking.HEADING_KEEP_S + 1
    w.walk()
    assert engine.published[-1].angle_move_amplitude == 0


def test_settle_waits_for_the_engine_to_actually_stop_and_records_how_long(walking):
    now = [0.0]
    engine, stands = FakeEngine(), []
    polls = {"n": 0}

    def is_walking():
        polls["n"] += 1
        now[0] += 0.1
        return polls["n"] < 8                     # engine stops after ~0.8 s

    engine.is_walking = is_walking
    w = walking.Walker(engine, stand_legs=lambda: stands.append(now[0]),
                       clock=lambda: now[0], sleep=lambda s: None, spawn=lambda f: f())
    w.walk()
    w.stop()
    assert stands and w.last_stop_s == pytest.approx(0.8, abs=0.15)



def test_gyro_offset_is_only_learned_after_the_body_has_been_still(walking):
    """Follow mode keeps moving the arms (via /move) before a march; even
    slow movement then twists the body, and an offset learned from it makes
    the hold steer the robot slowly sideways (2026-10-13: 'keeps turning to a
    side after marching for a certain time')."""
    now, rate = [0.0], [0.5]
    w, engine = _held_walker(walking, now, rate)
    _run(w, now, 5.0)                        # truly still: offset 0.5
    for _ in range(250):                     # 5 s of arm moves, body slowly twisting
        w.note_body_motion()
        rate[0] = 2.5                        # under the 3 deg/s fast-motion limit
        now[0] += 0.02
        w.sense()
    rate[0] = 0.5
    w.walk()
    _run(w, now, 10.0)                       # marching straight
    assert abs(w.yaw_deg) < 1.0


def test_a_move_counts_as_body_motion(pi_server):
    server, client, _, _ = pi_server
    client.post("/move", json=[{"servo_id": 13, "position": 700, "duration_ms": 100}])
    assert server._walker._body_moved_at is not None
