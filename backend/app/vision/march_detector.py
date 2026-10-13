"""Is the person marching? From the camera's 3D landmarks, frame by frame.

Follow mode uses this to start the robot's own walking engine (marching is
the engine's job; copying each step joint by joint would not balance).

Thigh angle: theta = arccos(t . d / |t|), t = knee - hip and d = the torso's
down axis (hip midpoint - shoulder midpoint). 0 deg standing, 90 deg thigh
horizontal. 3D because a knee raised toward the camera barely moves in the
2D picture (foreshortening); using the torso axis, not the camera's, keeps
a tilted camera from reading as a raise.

Detector, tuned on 2026-10-12 live logs and a randomized stress test
(tests/test_march_detector.py): each angle is low-passed (TAU_S). Each leg
keeps its own resting angle -- a slow average (REST_TAU_S) taken only while
that knee is down and near it (readings more than LOWER_DEG above it, which
may be a raise, only move it at the much slower REST_DRIFT_TAU_S, so small
raises from a weak-reading leg don't get averaged into its rest) -- and a
knee is UP when it stays RISE_DEG above it for
MIN_UP_S without falling back within LOWER_DEG (a knee raise lasts over
0.25 s; a camera noise spike doesn't, and a noise dip mid-raise doesn't
restart the count), DOWN again within LOWER_DEG. Relative, not fixed angles, because one leg often
reads much lower than the other (peaks L 23 / R 55 while marching) and the
resting angle isn't 0. An average, not the minimum, because noise drags a
minimum below the true rest and makes noise look like a rise.

A raise counts as a STEP only when the other knee is down (rejects frames
that read both legs as raised, a camera misread seen live). Marching starts
on two steps on alternating legs within START_WINDOW_S, OR on START_STEPS
steps in a steady rhythm (each within START_GAP_S of the last) from either
leg -- on the real camera one knee often reads too weak to count at all
(live recordings 2026-10-12: left peaks 15-23 deg vs right 33-55), and a
march that waits for it never starts; after that any step
keeps it going, and it stops after STOP_STEPS of the person's own step
intervals with no step (kept within STOP_MIN_S..STOP_MAX_S), so a missed step
doesn't end it -- or as soon as both knees have been still (within LOWER_DEG
of rest) for STILL_STOP_S, so stopping is followed promptly (2026-10-12:
"the robot keeps marching when I stop"). An unseen knee
(None) keeps its last reading.
"""

from __future__ import annotations

import math
from typing import Optional

_L_SHOULDER, _R_SHOULDER = 11, 12
_L_HIP, _R_HIP, _L_KNEE, _R_KNEE = 23, 24, 25, 26
# Shoulders and hips must be clearly seen. Knees get a looser gate than
# retargeting's 0.6: a knee raised toward the camera often drops below it.
MIN_VISIBILITY = 0.5
MIN_KNEE_VISIBILITY = 0.3

RISE_DEG = 12.0
LOWER_DEG = 6.0
MIN_UP_S = 0.04
TAU_S = 0.04
REST_TAU_S = 1.0
REST_DRIFT_TAU_S = 8.0
# First WARMUP_S: the resting angle is learned quickly and no step counts.
WARMUP_S = 0.5
WARMUP_TAU_S = 0.15
# A reading below the rest pulls it down quickly (a leg seen raised at the
# start settles once it comes down).
REST_DOWN_TAU_S = 0.3
# Longest frame gap one update may act on, s (dropped frames).
MAX_DT_S = 0.2
START_WINDOW_S = 2.0
START_STEPS = 3
START_GAP_S = 1.5
STOP_STEPS = 3.2
STOP_MIN_S = 2.0
STOP_MAX_S = 2.6
# Live recordings 2026-10-12: while stepping, the longest moment with
# neither knee above rest (3D and image combined) was 0.56 s in 7 sessions;
# 0.8 s keeps clear of that and stops promptly when the person stops.
STILL_STOP_S = 0.8
# Before any interval is known, assume this step interval, s.
DEFAULT_STEP_S = 0.6


def _point(lm: dict) -> tuple[float, float, float]:
    return lm["xw"], lm["yw"], lm["zw"]


def _seen(lm: dict, threshold: float) -> bool:
    return lm.get("visibility", 1.0) >= threshold and "xw" in lm


def thigh_raise_deg(body: list[dict], side: str) -> Optional[float]:
    """How far the thigh on MediaPipe's `side` ("l"/"r") is raised from
    straight down, degrees; None if a needed point isn't seen."""
    if len(body) <= _R_KNEE:
        return None
    hip, knee = (body[_L_HIP], body[_L_KNEE]) if side == "l" else (body[_R_HIP], body[_R_KNEE])
    torso = (body[_L_SHOULDER], body[_R_SHOULDER], body[_L_HIP], body[_R_HIP])
    if not all(_seen(lm, MIN_VISIBILITY) for lm in torso) or not _seen(knee, MIN_KNEE_VISIBILITY):
        return None
    ls, rs, lh, rh = (_point(lm) for lm in torso)
    down = [(lh[i] + rh[i] - ls[i] - rs[i]) / 2 for i in range(3)]
    thigh = [k - h for k, h in zip(_point(knee), _point(hip))]
    nd, nt = math.hypot(*down), math.hypot(*thigh)
    if nd < 1e-6 or nt < 1e-6:
        return None
    cos = sum(a * b for a, b in zip(thigh, down)) / (nd * nt)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


# Image-based knee lift. MediaPipe's flat image coordinates are its most
# accurate output; its depth (used by thigh_raise_deg) is its weakest,
# exactly where a raised knee comes toward the camera. Signal: how far the
# knee sits above the hip in the image, per unit of image torso height,
# scaled so a ~25-30 deg thigh raise moves it about RISE_DEG (standing
# knee-drop/torso ~0.8 measured 2026-10-12; a raise by theta shortens it by
# ~0.8 * (1 - cos theta)). Only differences matter: MarchDetector works on
# rises above each leg's own rest.
LIFT_2D_SCALE = 110.0
_MIN_TORSO_IMG = 0.05


def knee_lift_2d(body: list[dict], side: str) -> Optional[float]:
    """Image-based knee height on MediaPipe's `side`, in degree-like units
    (higher = knee raised); None if a needed point isn't seen."""
    if len(body) <= _R_KNEE:
        return None
    hip, knee = (body[_L_HIP], body[_L_KNEE]) if side == "l" else (body[_R_HIP], body[_R_KNEE])
    torso = (body[_L_SHOULDER], body[_R_SHOULDER], body[_L_HIP], body[_R_HIP])
    if not all(lm.get("visibility", 1.0) >= MIN_VISIBILITY and "y" in lm for lm in torso):
        return None
    if knee.get("visibility", 1.0) < MIN_KNEE_VISIBILITY or "y" not in knee:
        return None
    ls, rs, lh, rh = torso
    torso_len = (lh["y"] + rh["y"] - ls["y"] - rs["y"]) / 2
    if torso_len < _MIN_TORSO_IMG:
        return None
    return -LIFT_2D_SCALE * (knee["y"] - hip["y"]) / torso_len


class MarchDetector:
    def __init__(self) -> None:
        self.marching = False
        self._filt: dict[str, Optional[float]] = {"l": None, "r": None}
        self._rest = {"l": 0.0, "r": 0.0}
        self._up = {"l": False, "r": False}
        self._rising_since: dict[str, Optional[float]] = {"l": None, "r": None}
        self._last_t: Optional[float] = None
        self._first_t: Optional[float] = None
        self._last_step: Optional[tuple[float, str]] = None
        self._intervals: list[float] = []
        self._run = 0   # steps so far, each within START_GAP_S of the last
        self._active_at = 0.0   # last time either knee was above rest

    def update(self, l_deg: Optional[float], r_deg: Optional[float], now: float) -> bool:
        """Feed one frame's thigh angles (None = not seen); returns whether
        the person is marching."""
        dt = 0.0 if self._last_t is None else min(MAX_DT_S, max(0.0, now - self._last_t))
        self._last_t = now
        if self._first_t is None:
            self._first_t = now
        warming_up = now - self._first_t < WARMUP_S
        alpha = dt / (TAU_S + dt) if dt > 0 else 1.0
        for side, raw in (("l", l_deg), ("r", r_deg)):
            if raw is None:
                continue
            prev = self._filt[side]
            if prev is None:
                f = self._filt[side] = self._rest[side] = raw
            else:
                f = self._filt[side] = prev + alpha * (raw - prev)
                if warming_up:
                    tau = WARMUP_TAU_S
                elif f < self._rest[side]:
                    tau = REST_DOWN_TAU_S
                elif self._up[side] or self._rising_since[side] is not None:
                    tau = None
                elif f - self._rest[side] <= LOWER_DEG:
                    tau = REST_TAU_S
                else:
                    tau = REST_DRIFT_TAU_S
                if tau is not None:
                    self._rest[side] += dt / (tau + dt) * (f - self._rest[side])
            if warming_up:
                continue
            rise = f - self._rest[side]
            if rise > LOWER_DEG:
                self._active_at = now
            other = "r" if side == "l" else "l"
            if not self._up[side]:
                if self._rising_since[side] is None:
                    if rise >= RISE_DEG:
                        self._rising_since[side] = now
                elif rise <= LOWER_DEG:     # really came back down, not a noise dip
                    self._rising_since[side] = None
                elif now - self._rising_since[side] >= MIN_UP_S:
                    self._up[side] = True
                    if not self._up[other]:
                        self._step(side, now)
            elif rise <= LOWER_DEG:
                self._up[side] = False
                self._rising_since[side] = None
        if self.marching and (now - self._last_step[0] > self.stop_after_s()
                              or now - self._active_at > STILL_STOP_S):
            self.marching = False
        return self.marching

    def reset(self) -> None:
        self.__init__()

    def stop_after_s(self) -> float:
        """How long without a step ends the march: STOP_STEPS of the
        person's typical (median of recent) step interval, within limits."""
        recent = sorted(self._intervals[-5:]) or [DEFAULT_STEP_S]
        typical = recent[len(recent) // 2]
        return max(STOP_MIN_S, min(STOP_MAX_S, STOP_STEPS * typical))

    def _step(self, side: str, now: float) -> None:
        prev = self._last_step
        gap = None if prev is None else now - prev[0]
        if gap is not None and self.marching:
            self._intervals.append(gap)
        self._run = self._run + 1 if gap is not None and gap <= START_GAP_S else 1
        alternating = prev is not None and prev[1] != side and gap <= START_WINDOW_S
        if not self.marching and (alternating or self._run >= START_STEPS):
            self._intervals = [gap]
            self.marching = True
        self._last_step = (now, side)

