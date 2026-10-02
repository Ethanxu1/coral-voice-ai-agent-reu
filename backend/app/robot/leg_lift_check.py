"""Planning for the hardware leg-lift check (scripts/leg_lift_hardware_check.py).

Everything here is pure -- it decides WHAT to send; the script sends it
through the main server's /move (collision + fall check, sim mirror, the
normal sim->hardware unit conversion) and reads the robot's IMU.

The lift runs the real LegLiftController, fed a scripted "person" and
slowed down by the caller, so the robot does exactly what follow mode
would do -- parallelogram shift, knee coupled to hip, weight back in step
with the foot -- only slower.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from app.robot.angle_utils import rad_to_servo_units
from app.robot.servo_config import SERVO_ID_MAP
from app.validation import JOINT_LIMITS
from app.vision.leg_lift_controller import (
    ANKLES,
    LEG_JOINTS,
    LegLiftController,
    Phase,
    _shift,
    _stand,
)

CHECK_JOINTS: tuple[str, ...] = tuple(LEG_JOINTS) + tuple(ANKLES)
# Controller tick, in controller time. The script waits DT * slow between ticks.
DT = 0.05
# Stop the lift and bring the foot down if the torso leans this far from
# where it started. Sim lifts lean <= ~3 deg; 8 means something is wrong
# (a sign, a shift that is too small for the real robot) well before a fall.
ABORT_ROLL_DEG = 8.0
# Longest the landing may take before the plan gives up waiting for IDLE.
_SETTLE_LIMIT_S = 6.0


def stand_pose() -> dict[str, float]:
    return {j: _stand(j) for j in CHECK_JOINTS}


def single_joint_pose(joint: str, delta: float) -> dict[str, float]:
    """Stand, with one joint offset by `delta` rad."""
    pose = stand_pose()
    pose[joint] += delta
    return pose


def shift_pose(swing: str) -> dict[str, float]:
    """Stand with the weight moved over the foot that is NOT `swing`."""
    pose = stand_pose()
    for j, off in _shift(swing).items():
        pose[j] += off
    return pose


def to_moves(pose: dict[str, float], duration_ms: int) -> list[dict[str, int]]:
    """/move payload entries (uniform sim units; the server converts)."""
    return [
        {"servo_id": SERVO_ID_MAP[j], "position": rad_to_servo_units(v), "duration_ms": duration_ms}
        for j, v in pose.items()
    ]


def should_abort(roll_deg: float | None, baseline_deg: float) -> bool:
    """A missing reading counts as abort: mid-lift, flying blind is worse."""
    return roll_deg is None or abs(roll_deg - baseline_deg) > ABORT_ROLL_DEG


# One reading past ABORT_ROLL_DEG is not enough on the real robot. The tilt
# comes from the accelerometer, which also feels the body's jolts: on
# 2026-10-02 a clean left lift read +0.2 / -5.0 / -5.2 / +0.7 / -3.5 / -9.2
# deg tick to tick and stopped itself. A real tip keeps growing, so it must
# persist for ABORT_READINGS readings in a row -- unless it is past
# HARD_ABORT_DEG, which stops it at once.
ABORT_READINGS = 2
HARD_ABORT_DEG = 15.0


class LeanGuard:
    """Decides, one IMU reading at a time, when to stop a lift."""

    def __init__(self, baseline_deg: float):
        self.baseline = baseline_deg
        self._over = 0

    def update(self, roll_deg: float | None) -> bool:
        """True once the lift should stop. A missing reading counts as over."""
        if roll_deg is not None and abs(roll_deg - self.baseline) > HARD_ABORT_DEG:
            return True
        self._over = self._over + 1 if should_abort(roll_deg, self.baseline) else 0
        return self._over >= ABORT_READINGS


def shift_fraction(pose: dict[str, float], swing: str) -> float:
    """How far the hips have slid over the standing foot, 0 (stand) .. 1 (full)."""
    full = _shift(swing)["l_ank_roll"]
    return (pose["l_ank_roll"] - _stand("l_ank_roll")) / full


def foot_fraction(pose: dict[str, float], swing: str) -> float:
    """How high the swing foot is, as a fraction of its hip-pitch travel."""
    hip = f"{swing}_hip_pitch"
    lim = JOINT_LIMITS[hip]
    stand = _stand(hip)
    travel = (stand - lim.min) if swing == "l" else (lim.max - stand)
    return abs(pose[hip] - stand) / travel


def lean_breakdown(rows: list[tuple[float, float | None, float, float]]) -> dict[str, float | None]:
    """rows: (t, lean_deg, shift_fraction, foot_fraction) per tick.

    Separates the lean the hip slide causes (foot still down) from the lean
    once the foot is up -- they have different fixes."""
    def lean_at(cond):
        hit = next((r for r in rows if cond(r) and r[1] is not None), None)
        return None if hit is None else hit[1]

    leans = [r for r in rows if r[1] is not None]
    worst = max(leans, key=lambda r: abs(r[1]), default=None)
    up = [r for r in leans if r[3] >= 0.02]
    return {
        "after_shift": lean_at(lambda r: r[2] >= 0.98 and r[3] < 0.02),
        "foot_leaves": lean_at(lambda r: r[3] >= 0.02),
        "worst": None if worst is None else worst[1],
        "worst_shift": None if worst is None else worst[2],
        "worst_foot": None if worst is None else worst[3],
        "worst_foot_up": None if not up else max(up, key=lambda r: abs(r[1]))[1],
    }


# Real robot, 2026-10-02: with the whole weight on one leg, the standing
# leg's hip-roll servo gives a few degrees and the body sags ~10 deg toward
# the lifted foot (stable, foot clear). The sim's servos don't give, so it
# never shows this; a bigger hip slide barely helped (-10.9 -> -8.8 deg) and
# 1.3x already falls in sim. Instead the standing hip roll is moved back
# toward neutral while the foot is up (measured in sim: 0.1 rad of this
# tilts the body ~5.7 deg toward the standing foot). Faded in over the first
# STANCE_COMP_RAMP of foot travel so it arrives with the load, not before.
STANCE_COMP_RAMP = 0.05


def with_stance_comp(pose: dict[str, float], swing: str, comp_rad: float) -> dict[str, float]:
    """`pose` with the standing hip's roll eased back toward neutral by up to
    `comp_rad` while the `swing` foot is up."""
    if comp_rad == 0.0:
        return pose
    k = min(1.0, foot_fraction(pose, swing) / STANCE_COMP_RAMP)
    stance = "r" if swing == "l" else "l"
    out = dict(pose)
    out[f"{stance}_hip_roll"] += (comp_rad if swing == "l" else -comp_rad) * k
    return out


def _person(swing: str, fraction: float) -> dict[str, float]:
    """Retargeted legs with the robot's `swing` hip raised by `fraction` of
    its travel (the knee is derived by the controller, not read)."""
    frame = {j: _stand(j) for j in LEG_JOINTS}
    hip = f"{swing}_hip_pitch"
    lim = JOINT_LIMITS[hip]
    stand = _stand(hip)
    frame[hip] = stand - fraction * (stand - lim.min) if swing == "l" else \
        stand + fraction * (lim.max - stand)
    return frame


def lift_poses(
    swing: str,
    height: float,
    stop: Callable[[], bool] = lambda: False,
    raise_s: float = 1.0,
    hold_s: float = 3.0,
    lower_s: float = 1.0,
) -> Iterator[dict[str, float]]:
    """One leg lift, one pose per DT of controller time, ending at stand.

    `height` is the person's raise as a fraction of hip travel. When `stop()`
    turns true the person is treated as standing from then on, so the
    controller lowers the foot and slides the hips back its usual way.
    """
    ctl = LegLiftController()
    n_up, n_down = int(raise_s / DT), int(lower_s / DT)
    script = ([0.0] * int(0.5 / DT)
              + [height * (k + 1) / n_up for k in range(n_up)]
              + [height] * int(hold_s / DT)
              + [height * (1 - (k + 1) / n_down) for k in range(n_down)])
    stopped = False
    for fraction in script:
        stopped = stopped or stop()
        out = ctl.update(_person(swing, 0.0 if stopped else fraction), DT)
        yield {j: out[j] for j in CHECK_JOINTS}
    for _ in range(int(_SETTLE_LIMIT_S / DT)):
        if ctl.phase is Phase.IDLE:
            break
        out = ctl.update(_person(swing, 0.0), DT)
        yield {j: out[j] for j in CHECK_JOINTS}
