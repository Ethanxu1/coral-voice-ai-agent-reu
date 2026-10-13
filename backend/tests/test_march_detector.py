"""Telling marching from standing, shuffling and a single leg lift.

Read straight from MediaPipe's 3D world landmarks (not the robot's leg
targets, which are off by default on this branch). Known camera quirks it
must survive: jitter while standing still, knees that drop out of view when
raised toward the camera, and frames that read BOTH legs as raised.
"""

from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

import pytest

from app.vision.march_detector import (
    RISE_DEG,
    STOP_MAX_S,
    MarchDetector,
    thigh_raise_deg,
)

sys.path.insert(0, str(Path(__file__).parent / "vision"))
from test_pose_to_robot import _build_body  # noqa: E402

FPS = 20
DT = 1 / FPS
THIGH = 0.4  # m, hip to knee in the synthetic body


def raised(l_deg: float = 0.0, r_deg: float = 0.0) -> list[dict]:
    """A person facing the camera with each thigh raised forward (toward the
    camera: smaller z) by the given angle from straight down."""
    def knee(x, deg):
        a = math.radians(deg)
        return (x, THIGH * math.cos(a), -THIGH * math.sin(a))
    return _build_body(l_knee=knee(+0.1, l_deg), r_knee=knee(-0.1, r_deg))


# ── thigh_raise_deg ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("deg", [0, 15, 30, 45, 70, 90])
def test_thigh_angle_is_read_in_3d(deg):
    body = raised(l_deg=deg)
    assert thigh_raise_deg(body, "l") == pytest.approx(deg, abs=0.5)
    assert thigh_raise_deg(body, "r") == pytest.approx(0, abs=0.5)


def test_a_knee_raised_straight_at_the_camera_still_reads_raised():
    """In the 2D picture this knee barely moves (it comes toward the camera);
    in 3D it is a 60 degree raise."""
    body = raised(r_deg=60)
    assert body[26]["y"] == body[25]["y"]  # same image height as the other knee
    assert thigh_raise_deg(body, "r") == pytest.approx(60, abs=0.5)


def test_a_tilted_camera_does_not_read_as_a_raise():
    """'Down' is the torso axis, not the camera's: tilt the whole body."""
    body = raised()
    a = math.radians(15)
    for lm in body:
        y, z = lm["yw"], lm["zw"]
        lm["yw"], lm["zw"] = y * math.cos(a) - z * math.sin(a), y * math.sin(a) + z * math.cos(a)
    assert thigh_raise_deg(body, "l") == pytest.approx(0, abs=0.5)


def test_unseen_points_give_no_reading():
    body = raised(l_deg=40)
    body[25]["visibility"] = 0.1     # left knee
    assert thigh_raise_deg(body, "l") is None
    body = raised()
    body[11]["visibility"] = 0.1     # a shoulder: no torso axis
    assert thigh_raise_deg(body, "l") is None
    assert thigh_raise_deg([], "l") is None


# ── MarchDetector ────────────────────────────────────────────────────────────


def run(det, frames, t0=0.0):
    out = []
    for i, (a, b) in enumerate(frames):
        t = t0 + i * DT
        out.append((t, det.update(a, b, t)))
    return out


def step(side, up=40.0, frames_up=8, frames_down=4):
    lift = [(up, 0.0) if side == "l" else (0.0, up)] * frames_up
    return lift + [(0.0, 0.0)] * frames_down


def march(steps, up=40.0):
    frames = []
    for k in range(steps):
        frames += step("l" if k % 2 == 0 else "r", up)
    return frames


def test_alternating_knee_raises_are_marching():
    res = run(MarchDetector(), [(0.0, 0.0)] * 10 + march(4))
    assert not res[10][1]
    assert res[-1][1]
    first = next(t for t, m in res if m)
    assert first < 10 * DT + 2 * len(step("l")) * DT  # within the 2nd step


def test_standing_with_jitter_is_not_marching():
    rng = random.Random(0)
    frames = [(abs(rng.gauss(4, 4)), abs(rng.gauss(4, 4))) for _ in range(400)]
    assert not any(m for _, m in run(MarchDetector(), frames))


def test_shuffling_the_feet_is_not_marching():
    assert not any(m for _, m in run(MarchDetector(), march(6, up=9.0)))


def test_lifting_the_same_leg_twice_or_slowly_is_not_marching():
    assert not any(m for _, m in run(MarchDetector(), step("l") * 2))
    slow = (step("l") + [(0.0, 0.0)] * 30) * 4      # one lift every ~2 s
    assert not any(m for _, m in run(MarchDetector(), slow))


def test_a_rhythm_of_one_legs_raises_is_marching():
    """Deliberate (2026-10-12): when the camera misses the other knee, a
    march looks like one leg rising in rhythm. 3 quick raises start it."""
    assert run(MarchDetector(), step("l") * 4)[-1][1]


def test_both_legs_read_raised_at_once_is_not_marching():
    frames = ([(40.0, 0.0)] * 3 + [(40.0, 40.0)] * 10 + [(0.0, 0.0)] * 5) * 3
    assert not any(m for _, m in run(MarchDetector(), frames))


def test_stops_after_the_person_stops():
    det = MarchDetector()
    res = run(det, march(6))
    assert res[-1][1]
    rest = run(det, [(0.0, 0.0)] * int((STOP_MAX_S + 0.5) * FPS), t0=res[-1][0] + DT)
    assert rest[0][1]          # a pause between steps doesn't stop it at once
    assert not rest[-1][1]


def test_unseen_knees_hold_their_last_reading():
    frames = [(40.0, None)] * 8 + [(None, None)] * 4 + [(40.0, None)] * 8
    assert not any(m for _, m in run(MarchDetector(), frames))


def test_a_step_is_a_clear_rise_not_jitter():
    assert RISE_DEG >= 10


def test_real_landmarks_through_the_whole_chain():
    """Synthetic bodies through thigh_raise_deg and the detector."""
    det = MarchDetector()
    t, marching = 0.0, False
    for k in range(4):
        pose = raised(l_deg=40) if k % 2 == 0 else raised(r_deg=40)
        for body in [pose] * 8 + [raised()] * 4:
            marching = det.update(thigh_raise_deg(body, "l"), thigh_raise_deg(body, "r"), t)
            t += DT
    assert marching


# ── Real-world patterns, from the 2026-10-12 follow log ──────────────────────
# Peaks per 5 s while the user marched: L 44 / R 54 (detected, then dropped
# after ~1 s), L 23 / R 55 and L 33 / R 21 (never detected). One leg often
# reads much lower than the other, and the resting angle isn't 0.


def gait(l_rest, r_rest, l_peak, r_peak, steps, up_frames=8, down_frames=4, miss=()):
    """Alternating knee raises from each leg's own resting angle; steps in
    `miss` are not seen at all (the leg stays at rest)."""
    frames = []
    for k in range(steps):
        left = k % 2 == 0
        peak = l_peak if left else r_peak
        if k in miss:
            peak = l_rest if left else r_rest
        up = (peak, r_rest) if left else (l_rest, peak)
        frames += [up] * up_frames + [(l_rest, r_rest)] * down_frames
    return frames


def test_one_leg_reading_low_still_marches():
    """L 23 / R 55 from the log: the left raise never reached the old 25."""
    res = run(MarchDetector(), [(8.0, 9.0)] * 20 + gait(8, 9, 23, 55, 8))
    assert res[-1][1]


def test_the_other_leg_reading_low_still_marches():
    res = run(MarchDetector(), [(9.0, 7.0)] * 20 + gait(9, 7, 33, 21, 8))
    assert res[-1][1]


def test_a_high_resting_angle_still_marches():
    """Standing reads 16 deg (camera angle/posture): the old 15 deg 'down'
    level was never reached, so no step ever counted."""
    res = run(MarchDetector(), [(16.0, 17.0)] * 20 + gait(16, 17, 36, 40, 8))
    assert res[-1][1]


def test_a_missed_step_does_not_stop_the_march():
    """The log showed 'started' then 'stopped' ~1 s later while the user kept
    marching: one unseen step must not end it."""
    det = MarchDetector()
    # One unseen step at a time. Two in a row (knees still > STILL_STOP_S)
    # look exactly like stopping, which must stop it (2026-10-12).
    res = run(det, gait(8, 9, 44, 54, 12, miss=(5, 9)))
    first = next(i for i, (_, m) in enumerate(res) if m)
    assert all(m for _, m in res[first:])


def test_standing_with_jitter_around_a_high_resting_angle_is_not_marching():
    rng = random.Random(1)
    frames = [(16 + rng.gauss(0, 4), 17 + rng.gauss(0, 4)) for _ in range(600)]
    assert not any(m for _, m in run(MarchDetector(), frames))


def test_holding_one_leg_up_is_not_marching():
    frames = [(8.0, 9.0)] * 20 + [(50.0, 9.0)] * 100 + [(8.0, 9.0)] * 20
    assert not any(m for _, m in run(MarchDetector(), frames))


# ── Randomized stress test ───────────────────────────────────────────────────
# Ranges are wider than anything in the 2026-10-12 log: resting angle 0-20,
# one leg reading weak (rise only 14-20 above rest, like L 23 / R 55),
# camera noise, cadence from brisk to slow, and 1 in 8 steps not seen (never
# 2 in a row).


def _marcher(rng):
    rest = (rng.uniform(0, 20), rng.uniform(0, 20))
    strong, weak = rng.uniform(25, 50), rng.uniform(14, 20)
    rises = (strong, weak) if rng.random() < 0.5 else (weak, strong)
    step_s = rng.uniform(0.45, 0.8)
    noise = rng.uniform(0, 3)
    frames, t, missed_in_a_row = [], 0.0, 0
    for _ in range(int(2 / DT)):                      # standing first
        frames.append((rest[0] + rng.gauss(0, noise), rest[1] + rng.gauss(0, noise)))
    for k in range(14):
        side = k % 2
        # The first two are seen; at most 1 unseen in a row (2 in a row keep
        # the knees still past STILL_STOP_S -- indistinguishable from stopping).
        seen = k < 2 or missed_in_a_row == 1 or rng.random() > 1 / 8
        missed_in_a_row = 0 if seen else missed_in_a_row + 1
        n_up = int(step_s * 0.6 / DT)
        n_down = int(step_s * 0.4 / DT)
        # An unseen step still moves the knee a little: in the live recordings
        # (2026-10-12) at least one signal showed movement within 0.56 s
        # throughout every stepping stretch -- a "missed" step is a weak rise
        # (below RISE_DEG), not a frozen knee.
        rise = rises[side] if seen else rng.uniform(7, 10)
        for i in range(n_up + n_down):
            vals = [rest[0], rest[1]]
            if i < n_up:
                vals[side] += rise
            frames.append(tuple(v + rng.gauss(0, noise) for v in vals))
    return frames, int(2 / DT)


def _not_marcher(rng):
    rest = (rng.uniform(0, 20), rng.uniform(0, 20))
    noise = rng.uniform(0, 4)
    kind = rng.choice(["stand", "sway", "shuffle", "hold"])
    frames = []
    for i in range(int(12 / DT)):
        l, r = rest
        if kind == "sway":                            # slow weight shifts
            l += 5 * math.sin(i * DT * 2)
            r -= 5 * math.sin(i * DT * 2)
        elif kind == "shuffle" and (i // 12) % 2 == 0:  # small alternating lifts
            l += 8 if (i // 24) % 2 == 0 else 0
            r += 8 if (i // 24) % 2 == 1 else 0
        elif kind == "hold" and 40 <= i < 200:
            l += 45                                   # one leg held up
        frames.append((l + rng.gauss(0, noise), r + rng.gauss(0, noise)))
    return frames, kind


def _marcher_failures(seed):
    rng = random.Random(seed)
    failures = []
    for n in range(300):
        frames, start = _marcher(rng)
        res = run(MarchDetector(), frames)
        detected = [i for i, (_, m) in enumerate(res) if m]
        if any(m for _, m in res[:start]):
            failures.append((n, "marched while standing"))
        elif not detected:
            failures.append((n, "never detected"))
        elif res[detected[0]][0] - res[start][0] >= 2.5:
            failures.append((n, "detected late"))
        elif not all(m for _, m in res[detected[0]:len(res) - 1]):
            failures.append((n, "dropped mid-march"))
    return failures


def _false_triggers(seed):
    rng = random.Random(seed)
    out = []
    for n in range(300):
        frames, kind = _not_marcher(rng)
        if any(m for _, m in run(MarchDetector(), frames)):
            out.append((n, kind))
    return out


# Rates, not "every case": the generator's extremes (very fast marching with a
# leg rising only 14-15 deg, vs. vigorous 8 deg shuffling or +-5 deg swaying
# plus noise) overlap for any camera-based detector. Since the live
# recordings of 2026-10-12, sensitivity is favoured: the settings that start
# on the user's real marches false-trigger on ~3% of these synthetic
# non-marchers (worst case: the robot marches in place for a couple of s).
MAX_MISSED_RATE = 0.02
MAX_FALSE_RATE = 0.04


@pytest.mark.parametrize("seed", [2026, 11])
def test_stress_marchers_are_detected_and_stay_detected(seed):
    failures = _marcher_failures(seed)
    assert len(failures) <= MAX_MISSED_RATE * 300, failures


@pytest.mark.parametrize("seed", [7, 13])
def test_stress_non_marchers_rarely_trigger(seed):
    triggers = _false_triggers(seed)
    assert len(triggers) <= MAX_FALSE_RATE * 300, triggers


# ── Live recordings (logs/march_frames, 2026-10-12) ──────────────────────────
# Per-frame readings [L 3D, R 3D, L image, R image] from real follow sessions
# where the user marched. The left knee reads much weaker than the right.


def _replay(rows):
    d3, d2 = MarchDetector(), MarchDetector()
    t0 = rows[0][0]
    for t, (l3, r3, l2, r2) in rows:
        if d3.update(l3, r3, t - t0) | d2.update(l2, r2, t - t0):
            return t - t0
    return None


@pytest.mark.parametrize("name", ["095857", "095921", "100202"])
def test_real_marches_are_detected_within_4_seconds(name):
    path = Path(__file__).parent / "data" / "march_frames" / f"{name}.json"
    first = _replay(json.loads(path.read_text()))
    assert first is not None and first < 4.0



# ── Quick stop (2026-10-12: "the robot keeps marching when I stop") ─────────


def test_stops_soon_after_both_knees_go_still():
    det = MarchDetector()
    res = run(det, march(6))
    assert res[-1][1]
    rest = run(det, [(0.0, 0.0)] * int(2.0 * FPS), t0=res[-1][0] + DT)
    stopped_at = next(t for t, m in rest if not m) - rest[0][0]
    assert stopped_at <= 0.9
