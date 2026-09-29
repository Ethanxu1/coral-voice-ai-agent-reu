"""Lets the robot lift a leg visibly during follow mode without falling.

This robot cannot lift a foot visibly while its weight is spread across
both feet: every statically-safe leg pose clears under 1cm, and the
first visible one (12.7cm) topples it. What works, measured in
simulation with both legs:

  1. roll BOTH ankles ~0.15 rad toward the support side, ramped over
     ~0.9s -- this carries the centre of mass over the standing foot;
  2. wait ~1s for the weight to actually arrive;
  3. only then raise the swing leg, again ramped over ~0.9s.

Done that way, a full lift clears ~8cm and the robot stays up. Done any
other way it falls: shift and lift together topples it at any speed
short of a 9s lift, and -- the reason an earlier attempt failed -- any
of those steps applied as a single-frame jump rather than a ramp
topples it too. So this is a small state machine with every leg and
ankle joint rate-limited; nothing it outputs ever steps.

Driven with an explicit `dt` per call so it can be tested
deterministically, and stateful because the whole point is sequencing
across frames.
"""

from __future__ import annotations

from enum import Enum

from app.robot.hardware_angle_utils import HW_STAND_RAD
from app.validation import JOINT_LIMITS
from app.vision.pose_to_robot import _STAND_LEG_TARGETS, limit_leg_travel

ANKLES = ("l_ank_roll", "r_ank_roll")
LEG_JOINTS = tuple(_STAND_LEG_TARGETS)

# Ankle roll applied to both feet toward the support side. A negative
# delta moves the centre of mass toward the RIGHT foot (measured, not
# assumed), so lifting the left leg uses -SHIFT.
#
# Swept over a 10-case matrix (both legs; 20-60 deg raises; 0.5-1.0s;
# raise, hold 4s, lower): 0.10 fails on the robot's right leg -- the
# weight never arrives, consistent with the robot's documented
# right-heavy mass -- while 0.12, 0.14, 0.16 and 0.18 all pass 10/10.
# Around 0.20 the shift alone topples it. 0.15 sits mid-band.
SHIFT_RAD = 0.15
# Ramp times that reproduce the verified sequence.
SHIFT_SECONDS = 0.9
LIFT_SECONDS = 0.9
SETTLE_SECONDS = 1.0
# Swing-leg travel once the weight is across. Verified stable at 0.8
# (6.6cm clearance) and 1.0 (8.1cm); 0.8 keeps some margin.
LIFT_TRAVEL = 0.8
# Travel allowed when NOT in a supported lift -- the static safety limit.
IDLE_TRAVEL = 0.15
# Hysteresis on "is the person lifting a leg", as a fraction of the
# swing hip's travel: must clearly exceed the idle limit to start a
# lift, and drop well back to end one.
LIFT_ON = 0.20
LIFT_OFF = 0.10
# How long the leg must read as lowered before the lift is ended. Live
# vision drops frames (one session lost the person on ~half of them),
# and a dropped or knee-gated frame retargets the legs to stand -- which
# would otherwise read as "leg lowered" and abort the lift mid-air.
RELEASE_SECONDS = 0.3
_AT_GOAL = 0.005  # rad


class Phase(str, Enum):
    IDLE = "idle"
    SHIFTING = "shifting"
    SETTLING = "settling"
    LIFTING = "lifting"
    LOWERING = "lowering"
    UNSHIFTING = "unshifting"


def _stand(joint: str) -> float:
    if joint in _STAND_LEG_TARGETS:
        return _STAND_LEG_TARGETS[joint]
    return HW_STAND_RAD.get(joint, 0.0)


def _reach(joint: str) -> float:
    """Full travel from stand to whichever limit is further, used to
    size a joint's rate so a full-range ramp takes the stated time."""
    lim = JOINT_LIMITS[joint]
    s = _stand(joint)
    return max(lim.max - s, s - lim.min)


def _rate(joint: str) -> float:
    """Max speed (rad/s) for a joint.

    Ankles move at the rate of the verified shift -- the full SHIFT_RAD
    over SHIFT_SECONDS -- NOT a fraction of their full range. Sizing it
    by range made the shift finish in 0.3s, and the extra momentum
    rolled the robot past its resting lean and over while both feet
    were still down (traced: roll +3.5 -> +64 deg during settling).
    Legs cover their full range in LIFT_SECONDS.
    """
    if joint in ANKLES:
        return SHIFT_RAD / SHIFT_SECONDS
    return _reach(joint) / LIFT_SECONDS


def lift_fraction(side: str, targets: dict[str, float]) -> float:
    """How far a leg is raised, 0..1 of its hip-pitch travel from stand.
    Left hip lifts toward its minimum, right toward its maximum."""
    joint = f"{side}_hip_pitch"
    value = targets.get(joint)
    if value is None:
        return 0.0
    stand = _STAND_LEG_TARGETS[joint]
    lim = JOINT_LIMITS[joint]
    travel = (stand - lim.min) if side == "l" else (lim.max - stand)
    raised = (stand - value) if side == "l" else (value - stand)
    return 0.0 if travel <= 0 else max(0.0, min(1.0, raised / travel))


class LegLiftController:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.phase = Phase.IDLE
        self.swing: str | None = None
        self._settle_left = 0.0
        self._below = 0.0
        self._cmd: dict[str, float] = {j: _stand(j) for j in LEG_JOINTS + ANKLES}

    # -- helpers ---------------------------------------------------------

    def _slew(self, goals: dict[str, float], dt: float) -> None:
        for joint, goal in goals.items():
            step = _rate(joint) * dt
            cur = self._cmd[joint]
            delta = goal - cur
            self._cmd[joint] = goal if abs(delta) <= step else cur + (step if delta > 0 else -step)

    def _at(self, goals: dict[str, float]) -> bool:
        return all(abs(self._cmd[j] - g) <= _AT_GOAL for j, g in goals.items())

    # -- main ------------------------------------------------------------

    def update(self, desired: dict[str, float], dt: float) -> dict[str, float]:
        """`desired` is one frame of UNLIMITED retargeted targets. Returns
        it with every leg and ankle joint replaced by the controlled,
        rate-limited command. Other joints pass through untouched."""
        left, right = lift_fraction("l", desired), lift_fraction("r", desired)
        lifting_side = "l" if left > right else "r"
        asym = abs(left - right)

        self._below = self._below + dt if asym <= LIFT_OFF else 0.0
        self._advance(asym, lifting_side)

        goals = self._goals(desired)
        self._slew(goals, dt)

        if self.phase is Phase.SHIFTING and self._at({j: goals[j] for j in ANKLES}):
            self.phase, self._settle_left = Phase.SETTLING, SETTLE_SECONDS
        elif self.phase is Phase.SETTLING:
            self._settle_left -= dt
            if self._settle_left <= 0:
                self.phase = Phase.LIFTING
        elif self.phase is Phase.LOWERING and self._at(
            {j: goals[j] for j in (f"{self.swing}_hip_pitch", f"{self.swing}_knee")}
        ):
            self.phase = Phase.UNSHIFTING
        elif self.phase is Phase.UNSHIFTING and self._at({j: goals[j] for j in ANKLES}):
            self.phase, self.swing = Phase.IDLE, None

        out = dict(desired)
        out.update(self._cmd)
        return out

    def _advance(self, asym: float, side: str) -> None:
        released = self._below >= RELEASE_SECONDS
        if self.phase is Phase.IDLE and asym >= LIFT_ON:
            self.phase, self.swing = Phase.SHIFTING, side
        elif self.phase in (Phase.SHIFTING, Phase.SETTLING) and released:
            self.phase = Phase.UNSHIFTING
        elif self.phase is Phase.LIFTING and released:
            self.phase = Phase.LOWERING
        elif self.phase is Phase.LOWERING and asym >= LIFT_ON and side == self.swing:
            # Leg coming back up while the weight is still shifted.
            self.phase = Phase.LIFTING
        elif self.phase is Phase.UNSHIFTING and asym >= LIFT_ON:
            self.phase, self.swing = Phase.SHIFTING, side

    def _goals(self, desired: dict[str, float]) -> dict[str, float]:
        idle_legs = limit_leg_travel(
            {j: desired.get(j, _stand(j)) for j in LEG_JOINTS}, IDLE_TRAVEL
        )
        if self.phase is Phase.IDLE:
            return {**idle_legs, **{a: _stand(a) for a in ANKLES}}

        swing, support = self.swing, ("r" if self.swing == "l" else "l")
        shift = -SHIFT_RAD if swing == "l" else SHIFT_RAD
        shifted = self.phase in (Phase.SHIFTING, Phase.SETTLING, Phase.LIFTING, Phase.LOWERING)
        goals = {a: _stand(a) + (shift if shifted else 0.0) for a in ANKLES}

        # The robot stands on the support leg; it holds a known-good
        # stance, and hip roll (which fights the ankle shift) is neutral.
        for j in (f"{support}_hip_pitch", f"{support}_knee", "l_hip_roll", "r_hip_roll"):
            goals[j] = _stand(j)

        swing_joints = (f"{swing}_hip_pitch", f"{swing}_knee")
        if self.phase is Phase.LIFTING:
            lifted = limit_leg_travel(
                {j: desired.get(j, _stand(j)) for j in swing_joints}, LIFT_TRAVEL
            )
            goals.update(lifted)
        elif self.phase in (Phase.LOWERING, Phase.UNSHIFTING):
            goals.update({j: idle_legs[j] for j in swing_joints})
        else:
            # Weight still moving: foot stays planted.
            goals.update({j: _stand(j) for j in swing_joints})
        return goals
