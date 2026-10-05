"""Telling marching from standing and from a single leg lift.

Follow mode starts the robot's walking engine when the person marches. Input
per camera frame: how far each leg is raised (signed_lift, a fraction of
hip travel), or None when the camera didn't report that leg. Known camera
quirks it must survive: jitter while standing still, and frames that read
BOTH legs as raised (2026-10-02, the misread that tipped the robot).
"""

from __future__ import annotations

from app.vision.march_detector import STOP_AFTER_S, MarchDetector

FPS = 20
DT = 1 / FPS


def run(det, frames, t0=0.0):
    """Feed (l, r) frames at 20 fps; return (time, marching) per frame."""
    out = []
    for i, (l, r) in enumerate(frames):
        t = t0 + i * DT
        out.append((t, det.update(l, r, t)))
    return out


def step(side, up=0.6, frames_up=8, frames_down=4):
    """One knee raise and lower on `side`, the other leg down. 0.6 ~ the
    thigh raised 30 deg, measured through compute_joint_targets."""
    lift = [(up, 0.0) if side == "l" else (0.0, up)] * frames_up
    return lift + [(0.0, 0.0)] * frames_down


def march(steps):
    frames = []
    for k in range(steps):
        frames += step("l" if k % 2 == 0 else "r")
    return frames


def test_alternating_knee_raises_are_marching():
    res = run(MarchDetector(), [(0.0, 0.0)] * 10 + march(4))
    assert not res[10][1]                      # not on the first knee
    assert res[-1][1]                          # marching by the end
    first = next(t for t, m in res if m)
    assert first < 10 * DT + 2 * len(step("l")) * DT  # within the 2nd step


def test_standing_with_jitter_is_not_marching():
    import random

    rng = random.Random(0)
    frames = [(rng.gauss(0, 0.08), rng.gauss(0, 0.08)) for _ in range(400)]
    assert not any(m for _, m in run(MarchDetector(), frames))


def test_shuffling_the_feet_is_not_marching():
    """Small alternating raises (thigh ~10 deg) while standing about."""
    frames = []
    for k in range(6):
        frames += step("l" if k % 2 == 0 else "r", up=0.2)
    assert not any(m for _, m in run(MarchDetector(), frames))


def test_lifting_the_same_leg_again_is_not_marching():
    frames = step("l") * 4
    assert not any(m for _, m in run(MarchDetector(), frames))


def test_both_legs_read_raised_at_once_is_not_marching():
    frames = ([(0.6, 0.0)] * 3 + [(0.6, 0.6)] * 10 + [(0.0, 0.0)] * 5) * 3
    assert not any(m for _, m in run(MarchDetector(), frames))


def test_stops_after_the_person_stops():
    det = MarchDetector()
    res = run(det, march(6))
    assert res[-1][1]
    t_end = res[-1][0]
    rest = run(det, [(0.0, 0.0)] * int((STOP_AFTER_S + 0.5) * FPS), t0=t_end + DT)
    assert rest[0][1]          # a pause between steps doesn't stop it at once
    assert not rest[-1][1]


def test_unseen_legs_do_not_count_as_lowered_or_raised():
    frames = [(0.6, None)] * 8 + [(None, None)] * 4 + [(0.6, None)] * 8
    assert not any(m for _, m in run(MarchDetector(), frames))
