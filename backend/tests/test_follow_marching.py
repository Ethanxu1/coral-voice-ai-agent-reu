"""Follow mode hands the legs to the robot's walking engine while the person
marches (app/follow_marching.py) -- in place, never turning -- and takes
the legs back when they stop. In the simulator the detection still runs
(so the website can show it) but nothing is sent."""

from __future__ import annotations

import asyncio
import json
import math
import sys
from pathlib import Path

import pytest

from app.follow_marching import KEEPALIVE_S, MAX_MARCH_S, FollowMarching
from app.vision.march_detector import STOP_MAX_S as STOP_AFTER_S

sys.path.insert(0, str(Path(__file__).parent / "vision"))
from test_pose_to_robot import _build_body  # noqa: E402

DT = 0.05


@pytest.fixture
def anyio_backend():
    return "asyncio"


def person(l_deg=0.0, r_deg=0.0, heading=0.0) -> list[dict]:
    """Landmarks: thighs raised by l/r_deg; whole body turned `heading` deg
    toward the robot's left (MediaPipe's right-labelled side swings back)."""
    def knee(x, deg):
        a = math.radians(deg)
        return (x, 0.4 * math.cos(a), -0.4 * math.sin(a))
    body = _build_body(l_knee=knee(+0.1, l_deg), r_knee=knee(-0.1, r_deg))
    c, s = math.cos(math.radians(heading)), math.sin(math.radians(heading))
    for lm in body:   # about the vertical axis; right-labelled side (x < 0) goes back
        x, z = lm["xw"], lm["zw"]
        lm["xw"], lm["zw"] = x * c + z * s, -x * s + z * c
    return body


def march(steps, heading=0.0):
    frames = []
    for k in range(steps):
        up = person(l_deg=40, heading=heading) if k % 2 == 0 else person(r_deg=40, heading=heading)
        frames += [up] * 8 + [person(heading=heading)] * 4
    return frames


class Recorder:
    def __init__(self, fail=False):
        self.calls: list[bool] = []
        self.fail = fail

    async def __call__(self, walking: bool) -> None:
        self.calls.append(walking)
        if self.fail:
            raise RuntimeError("robot unreachable")


async def drive(fm, frames, t0=0.0):
    out = []
    for i, body in enumerate(frames):
        out.append(fm.update(body, t0 + i * DT))
        await asyncio.sleep(0)
    await asyncio.sleep(0.01)
    return out


@pytest.mark.anyio
async def test_marching_starts_the_walk_keeps_it_alive_then_stops_it():
    rec = Recorder()
    fm = FollowMarching(rec, send=True)
    frames = march(6)
    marching = await drive(fm, frames)
    assert marching[-1] and rec.calls and all(rec.calls)
    seconds = sum(marching) * DT
    assert seconds / KEEPALIVE_S - 1 <= len(rec.calls) <= seconds / KEEPALIVE_S + 2
    await drive(fm, [person()] * int((STOP_AFTER_S + 0.3) / DT), t0=len(frames) * DT)
    assert rec.calls[-1] is False and rec.calls.count(False) == 1


@pytest.mark.anyio
async def test_in_the_simulator_it_detects_but_sends_nothing():
    rec = Recorder()
    fm = FollowMarching(rec, send=False)
    marching = await drive(fm, march(6))
    assert marching[-1] and rec.calls == []
    await fm.close()
    assert rec.calls == []


@pytest.mark.anyio
async def test_a_long_march_is_capped_until_the_person_stops(monkeypatch):
    import app.follow_marching as fmod

    monkeypatch.setattr(fmod, "MAX_MARCH_S", 2.0)
    rec = Recorder()
    fm = FollowMarching(rec, send=True)
    frames = march(8)                          # 4.8 s of marching
    await drive(fm, frames)
    assert rec.calls[-1] is False              # stopped at the cap...
    n = len(rec.calls)
    await drive(fm, march(4), t0=len(frames) * DT)
    assert len(rec.calls) == n                 # ...and stays stopped while marching on
    t = (len(frames) + len(march(4))) * DT
    await drive(fm, [person()] * int((STOP_AFTER_S + 0.3) / DT), t0=t)
    t += (STOP_AFTER_S + 0.3)
    await drive(fm, march(4), t0=t)            # a fresh march starts again
    assert rec.calls[-1] is True
    assert MAX_MARCH_S == 20.0


@pytest.mark.anyio
async def test_closing_follow_mid_march_stops_the_walk():
    rec = Recorder()
    fm = FollowMarching(rec, send=True)
    await drive(fm, march(4))
    await fm.close()
    assert rec.calls[-1] is False


@pytest.mark.anyio
async def test_a_failing_robot_link_does_not_break_follow():
    fm = FollowMarching(Recorder(fail=True), send=True)
    marching = await drive(fm, march(4))
    assert marching[-1]
    await fm.close()


@pytest.mark.anyio
async def test_status_reports_marching():
    fm = FollowMarching(Recorder(), send=False)
    await drive(fm, march(4))
    assert fm.status() == {"marching": True, "robot_only": True}


# ── The whole follow loop, against a fake camera stream ──────────────────────


def _script(t: float) -> list[dict]:
    """Still, then 3 alternating knee raises, then still."""
    if 0.3 <= t < 2.1:
        k, phase = divmod(t - 0.3, 0.6)
        if phase < 0.4:
            return person(l_deg=40) if int(k) % 2 == 0 else person(r_deg=40)
    return person()


async def _run_follow(monkeypatch, robot_mode, fail_first_dispatch=False):
    import json
    import time

    from websockets.asyncio.server import serve

    import app.follow_controller as fc
    from app import config
    from app.state import state

    monkeypatch.setattr(state, "robot_mode", robot_mode)
    monkeypatch.setattr(config, "FOLLOW_MARCHING", True)
    monkeypatch.setattr(config, "RECORD_MARCH_FRAMES", False)
    t0 = time.monotonic()

    async def camera(conn):
        try:
            while True:
                await conn.send(json.dumps({"type": "pose_update",
                                            "body_landmarks": _script(time.monotonic() - t0)}))
                await asyncio.sleep(1 / 30)
        except Exception:
            return

    rec, statuses, dispatched = Recorder(), [], []

    async def dispatch(cmds, sim_only=None):
        dispatched.append(cmds)
        if fail_first_dispatch and len(dispatched) == 1:
            raise RuntimeError("robot server could not be reached")

    async def status(msg):
        statuses.append(msg)

    async with serve(camera, "localhost", 0) as server:
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr(fc, "VISION_WS_URL", f"ws://localhost:{port}/ws/pose")
        monkeypatch.setattr(fc, "VISION_HTTP_BASE", "http://localhost:1")
        follow = fc.FollowController(dispatch, walk_fn=rec)
        await follow.start_follow(status)
        await asyncio.sleep(2.1 + STOP_AFTER_S + 0.6 - (time.monotonic() - t0))
        await follow.stop_follow()
    return rec, [s for s in statuses if "marching" in s], dispatched


@pytest.mark.anyio
async def test_follow_on_the_robot_marches_with_the_person(monkeypatch):
    rec, marching_statuses, dispatched = await _run_follow(monkeypatch, "robot")
    walks = list(rec.calls)
    assert True in walks, "marching never started the robot's walk"
    assert walks[-1] is False
    assert [s["marching"] for s in marching_statuses] == [True, False]
    assert len(dispatched) > 20                # arms kept flowing


@pytest.mark.anyio
async def test_follow_in_the_simulator_shows_marching_but_sends_nothing(monkeypatch):
    rec, marching_statuses, _ = await _run_follow(monkeypatch, "sim")
    assert rec.calls == []
    assert [s["marching"] for s in marching_statuses] == [True, False]
    assert all(s["robot_only"] for s in marching_statuses)


def test_legs_out_of_view_are_reported(monkeypatch):
    """2026-10-12: a live test never marched because hips and knees were out
    of the camera's view, and nothing said so."""
    import app.follow_marching as fmod

    warnings = []
    monkeypatch.setattr(fmod.logger, "warning", lambda msg, *a: warnings.append(msg.format(*a)))
    fm = FollowMarching(Recorder(), send=False)
    body = person()
    for i in (23, 24, 25, 26):
        body[i]["visibility"] = 0.03
    t = 0.0
    while t < fmod.VISIBILITY_LOG_S + 1:
        fm.update(body, t)
        t += DT
    assert warnings and "hips/knees visible in only 0%" in warnings[0]



# ── Image-based detection and recording (2026-10-12 live runs) ──────────────


def flat_depth_person(l_lift=0.0, r_lift=0.0) -> list[dict]:
    """The camera misjudges depth: the 3D knees stay straight below the hips
    whatever happens, but in the flat image a raised knee clearly moves up
    toward the hip (lift = fraction of the standing knee drop)."""
    body = _build_body()
    for knee, hip, lift in ((25, 23, l_lift), (26, 24, r_lift)):
        drop = body[knee]["y"] - body[hip]["y"]
        body[knee]["y"] = body[hip]["y"] + drop * (1 - lift)
    return body


@pytest.mark.anyio
async def test_marching_is_seen_in_the_image_even_when_depth_says_nothing():
    rec = Recorder()
    fm = FollowMarching(rec, send=True)
    frames = [flat_depth_person()] * 20
    for k in range(8):
        up = flat_depth_person(l_lift=0.3) if k % 2 == 0 else flat_depth_person(r_lift=0.3)
        frames += [up] * 8 + [flat_depth_person()] * 4
    marching = await drive(fm, frames)
    assert marching[-1] and rec.calls and rec.calls[0] is True


def test_image_knee_lift_rises_when_the_knee_rises():
    from app.vision.march_detector import RISE_DEG, knee_lift_2d

    rest = knee_lift_2d(flat_depth_person(), "l")
    raised = knee_lift_2d(flat_depth_person(l_lift=0.3), "l")
    assert raised - rest > RISE_DEG
    assert knee_lift_2d(flat_depth_person(l_lift=0.3), "r") == pytest.approx(knee_lift_2d(flat_depth_person(), "r"))


@pytest.mark.anyio
async def test_a_follow_session_is_recorded_for_replay(tmp_path):
    import json

    fm = FollowMarching(Recorder(), send=False, record_dir=tmp_path)
    await drive(fm, march(4))
    await fm.close()
    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    rows = [json.loads(line) for line in files[0].read_text().splitlines()]
    assert len(rows) == len(march(4))
    assert set(rows[0]) == {"t", "read", "by_3d", "by_2d", "marching", "pts"}
    assert any(r["marching"] for r in rows)
    assert "image" not in files[0].read_text()



@pytest.mark.anyio
async def test_a_refused_opening_move_does_not_end_follow(monkeypatch):
    """2026-10-12: the robot refused follow's first move (still busy with the
    reset) and follow mode shut down -- no arms, no marching."""
    rec, marching_statuses, dispatched = await _run_follow(monkeypatch, "robot", fail_first_dispatch=True)
    assert len(dispatched) > 20
    assert True in rec.calls


# ── Only marching IN PLACE, in view (2026-10-12 live) ───────────────────────
# Walking toward the camera (body growing on screen 0.25 -> 0.61, hips moving)
# started a march, and it kept marching after the person left the frame.


def walking_toward_camera(n_steps=6) -> list[list[dict]]:
    """Knees rising alternately AND the body growing / moving on screen, at
    the speed recorded live (torso 0.265 -> 0.461 of the frame in 1.2 s)."""
    frames = []
    total = n_steps * 12
    for i in range(total):
        k, phase = divmod(i, 12)
        up = phase < 8
        body = person(l_deg=40 if up and k % 2 == 0 else 0, r_deg=40 if up and k % 2 else 0)
        grow = 1 + 1.4 * i / total                     # torso 0.25 -> ~0.6 on screen
        for lm in body:
            lm["x"] = 0.5 + (lm["x"] - 0.5) * grow + 0.1 * i / total
            lm["y"] = 0.5 + (lm["y"] - 0.5) * grow
        frames.append(body)
    return frames


@pytest.mark.anyio
async def test_walking_toward_the_camera_is_not_marching():
    rec = Recorder()
    fm = FollowMarching(rec, send=True)
    marching = await drive(fm, walking_toward_camera())
    assert not any(marching) and rec.calls == []


@pytest.mark.anyio
async def test_leaving_the_frame_stops_the_march_quickly():
    rec = Recorder()
    fm = FollowMarching(rec, send=True)
    frames = march(6)
    assert (await drive(fm, frames))[-1]
    gone = await drive(fm, [[]] * 20, t0=len(frames) * DT)
    first_stop = next(i for i, m in enumerate(gone) if not m) * DT
    assert first_stop <= 0.6
    assert rec.calls[-1] is False



def _recorded_bodies(name):
    path = Path(__file__).parent / "data" / "march_frames" / f"{name}_pts.json"
    rows = json.loads(path.read_text())
    out = []
    for t, pts in rows:
        body = [{"visibility": 0.0} for _ in range(33)]
        for k, (x, y, xw, yw, zw, vis) in pts.items():
            body[int(k)] = {"x": x, "y": y, "xw": xw, "yw": yw, "zw": zw, "visibility": vis}
        out.append((t, body))
    return out


def test_real_in_place_marching_passes_the_gate_and_walking_in_does_not():
    """Live 2026-10-12 (110604): marched in place 2.5-11.5 s, then walked
    toward the camera from ~15.5 s."""
    fm = FollowMarching(Recorder(), send=False)
    rows = _recorded_bodies("110604")
    t0 = rows[0][0]
    verdicts = [(t - t0, fm._in_place_and_in_view(body, t)) for t, body in rows]
    assert all(ok for t, ok in verdicts if 2.5 <= t <= 11.5)
    assert not all(ok for t, ok in verdicts if 15.5 <= t <= 17.6)



# ── 2026-10-13 live: unintended turns, slow stop ─────────────────────────────


@pytest.mark.anyio
async def test_turning_the_body_never_turns_the_robot():
    """2026-10-13: "just keep the marching at one place, remove any
    turning". A person marching while turned 45 deg (e.g. glancing at the
    laptop) only ever makes the robot march: walk_fn takes no turn at all."""
    import inspect

    assert list(inspect.signature(FollowMarching(Recorder(), send=True)._walk_fn).parameters) == ["walking"]
    rec = Recorder()
    fm = FollowMarching(rec, send=True)
    await drive(fm, march(8, heading=45.0))
    assert rec.calls and all(rec.calls)


@pytest.mark.anyio
async def test_the_stop_is_sent_at_once_even_while_a_renewal_is_on_its_way():
    import time

    sent: list[tuple[bool, float]] = []

    async def slow_walk(walking):
        sent.append((walking, time.monotonic()))
        if walking:
            await asyncio.sleep(0.5)            # a slow Wi-Fi round trip

    fm = FollowMarching(slow_walk, send=True)
    frames = march(6)
    t = 0.0
    for body in frames:
        fm.update(body, t)
        t += DT
        await asyncio.sleep(0)
    stop_decided = None
    for body in [person()] * 40:
        was = fm.marching
        fm.update(body, t)
        t += DT
        await asyncio.sleep(0)
        if was and not fm.marching:
            stop_decided = time.monotonic()
            break
    await asyncio.sleep(0.05)
    stops = [at for walking, at in sent if not walking]
    assert stop_decided is not None and stops
    assert stops[0] - stop_decided < 0.1
    await asyncio.sleep(0.6)
