"""Is the person marching? From how far each leg is raised, frame by frame.

Follow mode uses this to start the robot's own walking engine (marching is
the engine's job; copying each step joint by joint would not balance).

A knee raise counts as a STEP only when the other leg is down at that
moment. Two steps on alternating legs within START_WINDOW_S start marching;
no step for STOP_AFTER_S stops it. Requiring the other leg down rejects
frames that read both legs as raised -- a camera misread seen live
(2026-10-02) -- and lifting the same leg twice is not marching.
"""

from __future__ import annotations

# Raised / lowered, as a fraction of hip travel (signed_lift, UNCAPPED
# retargeting), with hysteresis. Measured through compute_joint_targets:
# thigh raised 15 deg -> 0.31, 30 deg -> 0.63, 45 deg -> 0.94. A march
# raises the thigh 30 deg or more; UP sits at ~15 deg so standing jitter
# and small shuffles stay out.
UP = 0.3
DOWN = 0.2
# Low-pass time constant for each leg's reading, s.
TAU = 0.1
# Longest frame gap one update may act on, s (dropped frames).
MAX_DT = 0.2
START_WINDOW_S = 1.5
STOP_AFTER_S = 1.2


class MarchDetector:
    def __init__(self) -> None:
        self.marching = False
        self._filt = {"l": 0.0, "r": 0.0}
        self._up = {"l": False, "r": False}
        self._last_t: float | None = None
        self._last_step: tuple[float, str] | None = None

    def update(self, l_lift: float | None, r_lift: float | None, now: float) -> bool:
        """Feed one frame (None = leg not seen); returns whether marching."""
        dt = 0.0 if self._last_t is None else min(MAX_DT, max(0.0, now - self._last_t))
        self._last_t = now
        alpha = dt / (TAU + dt) if dt > 0 else 1.0
        for side, raw in (("l", l_lift), ("r", r_lift)):
            if raw is None:
                continue
            f = self._filt[side] = self._filt[side] + alpha * (raw - self._filt[side])
            other = "r" if side == "l" else "l"
            if not self._up[side] and f >= UP:
                self._up[side] = True
                if not self._up[other]:
                    self._step(side, now)
            elif self._up[side] and f <= DOWN:
                self._up[side] = False
        if self.marching and now - self._last_step[0] > STOP_AFTER_S:
            self.marching = False
        return self.marching

    def _step(self, side: str, now: float) -> None:
        prev = self._last_step
        if prev is not None and prev[1] != side and now - prev[0] <= START_WINDOW_S:
            self.marching = True
        self._last_step = (now, side)
