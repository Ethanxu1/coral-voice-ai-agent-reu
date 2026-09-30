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
