"""Follow mode hands the legs to the robot's walking engine while the person
marches (app/follow_walking.py), and takes them back when they stop."""

from __future__ import annotations

import asyncio

import pytest

from app.follow_walking import (
    KEEPALIVE_S, TURN_START_DEG, TURN_STEP_DEG, FollowWalking, torso_turn_deg,
)
from app.vision.leg_lift_controller import _stand
from app.vision.march_detector import STOP_AFTER_S

DT = 0.05


@pytest.fixture
def anyio_backend():
    return "asyncio"


def person(l_raise: float = 0.0, r_raise: float = 0.0) -> dict[str, float]:
    """Retargeted leg targets with each hip raised by the given radians.
    Left hip lifts toward its minimum, right toward its maximum."""
    return {"l_hip_pitch": _stand("l_hip_pitch") - l_raise,
            "r_hip_pitch": _stand("r_hip_pitch") + r_raise}


def march_frames(steps: int) -> list[dict]:
    frames = []
    for k in range(steps):
        up = person(l_raise=0.6) if k % 2 == 0 else person(r_raise=0.6)
        frames += [up] * 8 + [person()] * 4
    return frames


async def drive(fw: FollowWalking, frames, t0=0.0):
    marching = []
    for i, f in enumerate(frames):
        marching.append(fw.update(f, t0 + i * DT))
        await asyncio.sleep(0)
    await asyncio.sleep(0.01)
    return marching


@pytest.mark.anyio
async def test_marching_starts_and_keeps_the_walk_alive_then_stops_it():
    calls: list[bool] = []

    async def walk_fn(walking: bool, turn: float = 0.0) -> None:
        calls.append(walking)

    fw = FollowWalking(walk_fn)
    frames = march_frames(6)
    marching = await drive(fw, frames)
    assert marching[-1] and calls and all(calls)
    marching_time = sum(marching) * DT
    # Renewed about every KEEPALIVE_S -- well inside the robot's timeout --
    # but not on every frame.
    assert marching_time / KEEPALIVE_S - 1 <= len(calls) <= marching_time / KEEPALIVE_S + 2

    still = [person()] * int((STOP_AFTER_S + 0.3) / DT)
    await drive(fw, still, t0=len(frames) * DT)
    assert calls[-1] is False and calls.count(False) == 1


@pytest.mark.anyio
async def test_closing_follow_mid_march_stops_the_walk():
    calls: list[bool] = []

    async def walk_fn(walking: bool, turn: float = 0.0) -> None:
        calls.append(walking)

    fw = FollowWalking(walk_fn)
    await drive(fw, march_frames(4))
    await fw.close()
    assert calls[-1] is False


@pytest.mark.anyio
async def test_a_failing_robot_link_does_not_break_follow():
    async def walk_fn(walking: bool, turn: float = 0.0) -> None:
        raise RuntimeError("robot unreachable")

    fw = FollowWalking(walk_fn)
    marching = await drive(fw, march_frames(4))
    assert marching[-1]
    await fw.close()


@pytest.mark.anyio
async def test_frames_without_legs_still_let_the_march_end():
    calls: list[bool] = []

    async def walk_fn(walking: bool, turn: float = 0.0) -> None:
        calls.append(walking)

    fw = FollowWalking(walk_fn)
    frames = march_frames(4)
    await drive(fw, frames)
    await drive(fw, [{}] * int((STOP_AFTER_S + 0.3) / DT), t0=len(frames) * DT)
    assert calls[-1] is False


# ── The whole follow loop, against a fake camera stream ──────────────────────


def _landmarks(side: str | None, deg: float = 40.0) -> list[dict]:
    """Camera landmarks of a person standing, or with one knee raised `deg`
    degrees (the vision tests' synthetic body), so the real retargeting --
    including follow mode's leg travel cap -- runs on them."""
    import math
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent / "vision"))
    from test_pose_to_robot import _build_body  # noqa: E402

    if side is None:
        return _build_body()
    dy, dz = 0.4 * math.cos(math.radians(deg)), -0.4 * math.sin(math.radians(deg))
    if side == "r":
        return _build_body(r_knee=(-0.1, dy, dz), r_ankle=(-0.1, dy + 0.4, dz),
                           img_r_knee=(0.45, 0.75))
    return _build_body(l_knee=(0.1, dy, dz), l_ankle=(0.1, dy + 0.4, dz),
                       img_l_knee=(0.55, 0.75))


def _script(t: float) -> list[dict]:
    """The person: still, then 3 alternating knee raises, then still."""
    if 0.3 <= t < 2.1:
        k, phase = divmod(t - 0.3, 0.6)
        if phase < 0.4:
            return _landmarks("l" if int(k) % 2 == 0 else "r")
    return _landmarks(None)


@pytest.mark.anyio
async def test_follow_on_the_robot_marches_with_the_person_and_stops(monkeypatch):
    import json
    import time

    from websockets.asyncio.server import serve

    import app.follow_controller as fc
    from app import config
    from app.state import state

    monkeypatch.setattr(state, "robot_mode", "robot")
    monkeypatch.setattr(config, "FOLLOW_WALKING", True)
    monkeypatch.setattr(config, "HARDWARE_LEG_MIMICRY", False)
    monkeypatch.setattr(config, "ENABLE_FOLLOW_SAFETY", False)
    monkeypatch.setattr(config, "ENABLE_LEG_TRACKING", True)
    t0 = time.monotonic()

    async def camera(conn):
        try:
            while True:
                frame = _script(time.monotonic() - t0)
                await conn.send(json.dumps({"type": "pose_update", "body_landmarks": frame}))
                await asyncio.sleep(1 / 30)
        except Exception:
            return

    walk_calls: list[bool] = []
    statuses: list[dict] = []
    streamed: list[list] = []

    async def walk_fn(walking, turn=0.0):
        walk_calls.append(walking)

    async def dispatch(cmds, sim_only=None):
        streamed.append(cmds)

    async def status(msg):
        statuses.append(msg)

    async with serve(camera, "localhost", 0) as server:
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr(fc, "VISION_WS_URL", f"ws://localhost:{port}/ws/pose")
        monkeypatch.setattr(fc, "VISION_HTTP_BASE", "http://localhost:1")
        follow = fc.FollowController(dispatch, stream_fn=dispatch, walk_fn=walk_fn)
        await follow.start_follow(status)
        await asyncio.sleep(2.1 + STOP_AFTER_S + 0.6 - (time.monotonic() - t0))
        await follow.stop_follow()

    assert True in walk_calls, "marching never started the robot's walk"
    assert walk_calls[-1] is False and walk_calls.index(False) > walk_calls.index(True)
    assert [s["marching"] for s in statuses if "marching" in s] == [True, False]
    assert len(streamed) > 40  # arms kept streaming throughout


# ── Turning while marching ───────────────────────────────────────────────────


def shoulders(yaw_deg: float) -> list[dict]:
    """Landmarks with the shoulder line turned `yaw_deg` toward the side
    that drives the ROBOT'S LEFT arm -- MediaPipe's RIGHT-labelled shoulder
    (pose_to_robot maps right_* landmarks onto the robot's l_* joints) swings
    back, away from the camera (larger z is farther)."""
    import math

    half = 0.2
    c, s_ = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    body = [{"xw": 0.0, "yw": 0.0, "zw": 0.0, "visibility": 0.0} for _ in range(33)]
    body[12] = {"xw": -half * c, "yw": -0.5, "zw": half * s_, "visibility": 1.0}
    body[11] = {"xw": half * c, "yw": -0.5, "zw": -half * s_, "visibility": 1.0}
    return body


def test_torso_turn_reads_the_shoulder_line():
    assert torso_turn_deg(shoulders(0)) == pytest.approx(0, abs=1e-6)
    assert torso_turn_deg(shoulders(30)) == pytest.approx(30)
    assert torso_turn_deg(shoulders(-40)) == pytest.approx(-40)
    hidden = shoulders(30)
    hidden[11]["visibility"] = 0.2
    assert torso_turn_deg(hidden) is None


@pytest.mark.anyio
async def test_turning_while_marching_turns_the_robot_the_same_way_as_the_arms():
    """Sides follow the arm mapping: turning toward the side that drives the
    robot's LEFT arm turns the robot to its own left (positive turn on the
    walking engine, confirmed on the robot). With the camera flip that is a
    shadow, not a mirror: the person turns to their left, so does the
    robot."""
    sent: list[tuple[bool, float]] = []

    async def walk_fn(walking: bool, turn: float = 0.0) -> None:
        sent.append((walking, turn))

    fw = FollowWalking(walk_fn)
    frames = march_frames(4)
    t = 0.0
    for f in frames:                       # facing the camera
        fw.update(f, t, shoulders(0))
        t += DT
        await asyncio.sleep(0)
    assert sent and all(turn == 0 for _, turn in sent)
    for f in march_frames(6):              # turned toward the left side
        fw.update(f, t, shoulders(TURN_START_DEG + 15))
        t += DT
        await asyncio.sleep(0)
    await asyncio.sleep(0.01)
    assert sent[-1] == (True, TURN_STEP_DEG)
    for f in march_frames(6):              # turned the other way
        fw.update(f, t, shoulders(-(TURN_START_DEG + 15)))
        t += DT
        await asyncio.sleep(0)
    await asyncio.sleep(0.01)
    assert sent[-1] == (True, -TURN_STEP_DEG)


@pytest.mark.anyio
async def test_a_slight_twist_does_not_turn_the_robot():
    sent: list[tuple[bool, float]] = []

    async def walk_fn(walking: bool, turn: float = 0.0) -> None:
        sent.append((walking, turn))

    fw = FollowWalking(walk_fn)
    t = 0.0
    for f in march_frames(8):
        fw.update(f, t, shoulders(TURN_START_DEG - 8))
        t += DT
        await asyncio.sleep(0)
    await asyncio.sleep(0.01)
    assert sent and all(turn == 0 for _, turn in sent)
