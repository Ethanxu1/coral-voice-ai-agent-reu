"""Lets the robot lift a leg during follow mode, upright and without falling.

This robot cannot lift a foot visibly while its weight is spread across
both feet: every statically-safe leg pose clears under 1cm, and the
first visible one (12.7cm) topples it. The weight has to be moved over
the standing foot first -- and HOW it is moved decides how the lift looks.

Tilting the whole robot sideways (both ankles only) works but leans the
torso 10-13 deg, makes the two legs lift to different heights (the lean
itself raises the swing side, and differs per side because this robot is
right-heavy), and needs a ~1s pause to let the tilting body settle.

What this does instead is what a person does: slide the hips over the
standing foot with the torso vertical. Both ankles roll by A and both
hips roll by 1.5*A the same way, so the legs form a parallelogram --
pelvis moves ~27mm sideways, torso stays within ~2 deg of upright, both
feet stay flat. Measured with it:

  torso roll during a lift          <= 0.7 deg   (was 10-13)
  left vs right lift height         5.2 vs 5.2cm (was unequal)
  shift + lift, sequential          stable down to 0.2s + 0.2s, no pause
  shift + lift, fully concurrent    falls, both legs, at any speed

So the one thing that must still be sequenced is that the swing foot
leaves only once the shift has arrived -- about 0.25s. Everything is
rate-limited; nothing this outputs ever steps.
"""

from __future__ import annotations

from enum import Enum

from app.robot.hardware_angle_utils import HW_STAND_RAD
from app.validation import JOINT_LIMITS
from app.vision.pose_to_robot import _STAND_LEG_TARGETS, limit_leg_travel

ANKLES = ("l_ank_roll", "r_ank_roll")
HIP_ROLLS = ("l_hip_roll", "r_hip_roll")
LEG_JOINTS = tuple(_STAND_LEG_TARGETS)

# Parallelogram shift. A negative delta moves the centre of mass toward
# the RIGHT foot (measured), so lifting the left leg uses -ANKLE_SHIFT.
# Hips roll the same way at HIP_RATIO x the ankles to keep the torso
# upright: at 1.5 torso roll settles at +1.8 deg with a 27mm pelvis shift
# and both feet down; at 2.5 and above it falls over.
ANKLE_SHIFT = 0.12
HIP_RATIO = 1.5
SHIFT_SECONDS = 0.25
# Swing-leg joints cover their full range in this long. Stable down to a
# 0.2s lift once the shift has arrived; the person's own movement is
# usually the slower of the two.
LIFT_SECONDS = 0.3
# Swing-leg travel during a supported lift.
LIFT_TRAVEL = 0.8
# Leg travel allowed when NOT in a supported lift. Near zero on purpose:
# any lift made before the weight has shifted is unsupported, and even a
# partial one starts the robot rolling. When dropped frames then delay
# the shift, the shift arrives against an already-moving body, overshoots
# past upright and the robot falls the other way (traced). Below the lift
# threshold a lift is under 1cm anyway, so nothing visible is lost.
IDLE_TRAVEL = 0.03
# "Is the person lifting a leg", as a fraction of swing-hip travel.
# Deliberately low. Until a lift is detected the leg follows the person
# unsupported, and an unsupported partial lift leans the robot (0.15 of
# travel measured at ~7 deg) -- so the shift must start almost at once.
LIFT_ON = 0.08
LIFT_OFF = 0.04
# How long the leg must read as lowered before the lift ends. Dropped or
# knee-gated vision frames retarget the legs to stand, which would
# otherwise read as "leg lowered" and abort a lift mid-air.
RELEASE_SECONDS = 0.2
# How long a lift must read as present before the hips slide. The
# detection threshold is low, so without this, vision jitter alone set
# off ~6 spurious hip slides per 20s while the person stood still.
ONSET_SECONDS = 0.1
# Largest time step one update may act on. After a run of dropped
# frames the next update sees a long dt, and a rate limiter given a long
# dt moves the whole distance at once -- a step, which is exactly what
# topples this robot. Capping it means the robot simply moves a little
# slower across a gap instead of jumping.
MAX_DT = 0.06
# Phase decisions (lift started / lift ended) use the lift reading
# low-passed with this time constant. With the thresholds this low,
# raw vision jitter kept resetting the "leg is down" timer, so a lift
# was never confirmed as ended: the robot stayed shifted onto one foot
# after the person put their leg down, and slowly rolled over.
DECISION_TAU = 0.1
# While standing on one foot the lifted leg rises as fast as the person
# does but comes down no faster than this (fraction of each joint's
# travel per second). A dropped or knee-gated frame reads as "leg at
# stand"; followed directly, a run of them pumped the lifted leg up and
# down and tipped the robot. Rate-limiting only the DOWNWARD direction
# means one bad frame nudges the leg by a few percent and the next good
# frame restores it, while a real lowering still comes through, smoothly.
LOWER_RATE = 2.0
_AT_GOAL = 0.005  # rad


class Phase(str, Enum):
    IDLE = "idle"
    SHIFTING = "shifting"
    LIFTING = "lifting"
    LOWERING = "lowering"
    UNSHIFTING = "unshifting"


def _stand(joint: str) -> float:
    if joint in _STAND_LEG_TARGETS:
        return _STAND_LEG_TARGETS[joint]
    return HW_STAND_RAD.get(joint, 0.0)


def _reach(joint: str) -> float:
    lim = JOINT_LIMITS[joint]
    s = _stand(joint)
    return max(lim.max - s, s - lim.min)


def _rate(joint: str) -> float:
    """Max speed (rad/s). Shift joints move at the rate that completes the
    shift in SHIFT_SECONDS -- sized from the shift itself, NOT the joint's
    range. Sizing ankles by range once made a shift finish 3x too fast and
    the momentum toppled the robot with both feet still down."""
    if joint in ANKLES:
        return ANKLE_SHIFT / SHIFT_SECONDS
    if joint in HIP_ROLLS:
        return HIP_RATIO * ANKLE_SHIFT / SHIFT_SECONDS
    return _reach(joint) / LIFT_SECONDS


def _lift_side_only(joint: str, value: float) -> float:
    """Clamp a swing-leg joint so it can only move in the LIFT direction
    from stand, never past stand the other way. Past stand the leg is
    straighter, i.e. longer, and planting a too-long leg while the hips are
    slid over pushed the robot onto its side."""
    stand = _STAND_LEG_TARGETS[joint]
    return min(value, stand) if _lift_sign(joint) < 0 else max(value, stand)


def _lift_sign(joint: str) -> float:
    """Direction a swing-leg joint moves to LIFT the leg (mirrored sim
    signs: left hip flexes negative and left knee bends positive; the
    right leg is the mirror)."""
    return -1.0 if joint in ("l_hip_pitch", "r_knee") else 1.0


def _shift(swing: str) -> dict[str, float]:
    """Offsets from stand that put the weight on the non-swing foot."""
    sign = -1.0 if swing == "l" else 1.0
    return {
        **{a: sign * ANKLE_SHIFT for a in ANKLES},
        **{h: sign * HIP_RATIO * ANKLE_SHIFT for h in HIP_ROLLS},
    }


def signed_lift(side: str, targets: dict[str, float]) -> float:
    """How far a leg is raised as a fraction of its hip-pitch travel,
    SIGNED and unclamped, so jitter about stand averages to zero. Left hip
    lifts toward its minimum, right toward its maximum."""
    joint = f"{side}_hip_pitch"
    value = targets.get(joint)
    if value is None:
        return 0.0
    stand = _STAND_LEG_TARGETS[joint]
    lim = JOINT_LIMITS[joint]
    travel = (stand - lim.min) if side == "l" else (lim.max - stand)
    raised = (stand - value) if side == "l" else (value - stand)
    return 0.0 if travel <= 0 else raised / travel


def lift_fraction(side: str, targets: dict[str, float]) -> float:
    """`signed_lift` clamped to 0..1."""
    return max(0.0, min(1.0, signed_lift(side, targets)))


class LegLiftController:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.phase = Phase.IDLE
        self.swing: str | None = None
        self._below = 0.0
        self._above = 0.0
        # Swing leg's held lift, per joint, as rad from stand in the lift
        # direction (see LOWER_RATE).
        self._held_swing: dict[str, float] | None = None
        self._lift_f = {"l": 0.0, "r": 0.0}
        self._dt = 0.0
        self._cmd: dict[str, float] = {j: _stand(j) for j in LEG_JOINTS + ANKLES}

    def _slew(self, goals: dict[str, float], dt: float) -> None:
        for joint, goal in goals.items():
            step = _rate(joint) * dt
            cur = self._cmd[joint]
            delta = goal - cur
            self._cmd[joint] = goal if abs(delta) <= step else cur + (step if delta > 0 else -step)

    def _at(self, goals: dict[str, float], joints) -> bool:
        return all(abs(self._cmd[j] - goals[j]) <= _AT_GOAL for j in joints)

    def update(self, desired: dict[str, float], dt: float) -> dict[str, float]:
        """`desired` is one frame of UNLIMITED retargeted targets. Returns
        it with every leg and ankle joint replaced by the controlled,
        rate-limited command. Other joints pass through untouched."""
        dt = min(dt, MAX_DT)
        # Phase decisions use each leg's SIGNED lift, low-passed, with the
        # difference taken afterwards. Filtering |left - right| instead
        # does not work: jitter through an absolute value averages ~0.07,
        # permanently above LIFT_OFF, so a lowered leg was never confirmed
        # and the robot stayed shifted onto one foot until it rolled over.
        alpha = dt / (DECISION_TAU + dt)
        for s_ in ("l", "r"):
            self._lift_f[s_] += alpha * (signed_lift(s_, desired) - self._lift_f[s_])
        lf = max(0.0, self._lift_f["l"])
        rf = max(0.0, self._lift_f["r"])
        side = "l" if lf > rf else "r"
        asym_f = abs(lf - rf)
        self._below = self._below + dt if asym_f <= LIFT_OFF else 0.0
        self._above = self._above + dt if asym_f >= LIFT_ON else 0.0
        self._dt = dt
        self._advance(asym_f, side)

        goals = self._goals(desired)
        self._slew(goals, dt)

        shift_joints = ANKLES + HIP_ROLLS
        if self.phase is Phase.SHIFTING and self._at(goals, shift_joints):
            self.phase = Phase.LIFTING
        elif self.phase is Phase.LOWERING and self._at(
            goals, (f"{self.swing}_hip_pitch", f"{self.swing}_knee")
        ):
            self.phase = Phase.UNSHIFTING
        elif self.phase is Phase.UNSHIFTING and self._at(goals, shift_joints):
            self.phase, self.swing = Phase.IDLE, None

        out = dict(desired)
        out.update(self._cmd)
        return out

    def _advance(self, asym: float, side: str) -> None:
        released = self._below >= RELEASE_SECONDS
        onset = self._above >= ONSET_SECONDS
        if self.phase is Phase.IDLE and onset:
            self.phase, self.swing = Phase.SHIFTING, side
        elif self.phase is Phase.SHIFTING and released:
            self.phase = Phase.UNSHIFTING
        elif self.phase is Phase.LIFTING and released:
            self.phase = Phase.LOWERING
        elif self.phase is Phase.LOWERING and asym >= LIFT_ON and side == self.swing:
            self.phase = Phase.LIFTING
        elif self.phase is Phase.UNSHIFTING and onset:
            # Re-shift -- toward whichever side is lifting now.
            self.phase, self.swing = Phase.SHIFTING, side

    def _goals(self, desired: dict[str, float]) -> dict[str, float]:
        idle_legs = limit_leg_travel(
            {j: desired.get(j, _stand(j)) for j in LEG_JOINTS}, IDLE_TRAVEL
        )
        if self.phase is Phase.IDLE:
            return {**idle_legs, **{a: _stand(a) for a in ANKLES}}

        swing = self.swing
        support = "r" if swing == "l" else "l"
        shifted = self.phase is not Phase.UNSHIFTING
        offsets = _shift(swing) if shifted else {j: 0.0 for j in ANKLES + HIP_ROLLS}
        goals = {j: _stand(j) + offsets[j] for j in ANKLES + HIP_ROLLS}

        # The robot stands on the support leg; it holds its stance.
        for j in (f"{support}_hip_pitch", f"{support}_knee"):
            goals[j] = _stand(j)

        swing_joints = (f"{swing}_hip_pitch", f"{swing}_knee")
        if self.phase is Phase.LIFTING:
            limited = limit_leg_travel(
                {j: desired.get(j, _stand(j)) for j in swing_joints}, LIFT_TRAVEL
            )
            held = {}
            for j in swing_joints:
                wanted = abs(_lift_side_only(j, limited[j]) - _stand(j))
                previous = self._held_swing.get(j, 0.0) if self._held_swing else 0.0
                floor = previous - LOWER_RATE * _reach(j) * self._dt
                held[j] = max(wanted, floor, 0.0)
            self._held_swing = held
            for j, amount in held.items():
                goals[j] = _lift_side_only(j, _stand(j) + _lift_sign(j) * amount)
        elif self.phase is Phase.SHIFTING:
            self._held_swing = None
            # Weight not across yet: foot fully planted, so the only thing
            # moving is the hip slide. Even a small unsupported lift here
            # leans the robot before the shift can catch it.
            goals.update({j: _stand(j) for j in swing_joints})
        else:  # LOWERING, UNSHIFTING -- back down to stand, never past it.
            goals.update({j: _lift_side_only(j, idle_legs[j]) for j in swing_joints})
        return goals
