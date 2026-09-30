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
# During a lift the knee is NOT copied from the person: it bends by this
# many rad per rad of hip flex, so the foot always rises and lowers under
# the hip. Traced live: the camera's knee reading is unreliable when the
# knee comes toward it (ankle depth flattened, or ankle not seen at all),
# so the robot lifted a STRAIGHT leg -- hip raised, knee at stand -- and on
# the way down the knee straightened before the hip. Straight-leg raises put
# the foot up to 95mm forward, rolled the robot ~10 deg and TURNED it 20-46
# deg; the foot also kicked forward just before landing.
# Sweep (foot forward within 15mm of the floor / peak clearance, 45 deg):
#   1.0  27mm / 4.2cm    1.8  5mm / 6.8cm    2.2  0mm, but the knee hits its
#   limit by a 30 deg raise, so small and large raises look the same.
KNEE_PER_HIP = 1.8
# Leg travel allowed when NOT in a supported lift: none -- the legs hold
# stand until a lift is detected.
#   - Any lift before the weight has shifted is unsupported; even a partial
#     one starts the robot rolling, and a shift arriving late against a
#     moving body overshoots and topples it (traced).
#   - Even a tiny allowance (0.03 of travel, <1cm, invisible as mimicry)
#     let camera jitter flip the hip rolls back and forth every frame, which
#     rocked the pelvis sideways -- the "hips sway when setting the foot
#     down" report. Under realistic noise, holding still cut hip direction
#     reversals during a landing from 4.8 to 0.7 and settle time from 2.3s
#     to 1.5s, with no change to the lift itself.
IDLE_TRAVEL = 0.0
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

# Landing. Three problems, each traced:
#   1. The foot came down at full speed right to the floor (~4.5 deg rock).
#   2. A 0.25s linear hip slide-back overshot into an oscillation (roll
#      -3.9 / +1.9 / -0.8, pitch rocking to +4.5 deg).
#   3. The one that caused falls in the live pipeline: with the hips still
#      shifted, the real foot touched the floor while the command was still
#      easing in, and the leg kept extending against the floor for ~0.6s.
#      That pushes the landing side of the pelvis up; the robot tipped
#      steadily and rolled over before a separate slide-back could start.
#      (Waiting after touchdown made it worse for the same reason.)
# So, within TOUCHDOWN_ZONE of the floor (fraction of each joint's travel):
#   - the foot comes down no faster than TOUCHDOWN_RATE (fraction/s);
#   - on the way back UP the foot may not outrun the shift in place
#     (_supported_lift), or re-lifting mid-landing topples it.
# And within WEIGHT_ZONE of the floor the weight comes back IN STEP with
# the foot (_landing_weight_fraction), so it is centred as the foot lands.
# Whatever shift remains after touchdown eases out over UNSHIFT_SECONDS.
TOUCHDOWN_ZONE = 0.25
TOUCHDOWN_RATE = 0.7
# Reported live: the foot was set down with the hips still leaned over,
# and the robot straightened ~a second later. With the weight coupled only
# to the last TOUCHDOWN_ZONE, it started back ~10mm above the floor, and
# the pelvis was still 75-92% across when the foot touched (live pipeline,
# robot-R). Spread over the lower half of the lift instead, under noise:
# worst lean at touchdown 76% -> 15%, worst landing roll 3.0 -> 2.8 deg,
# 12/12 stay up; holding a leg part-raised anywhere from 12-40 deg stays up
# (24/24) and leans at most 1.7 deg. 0.7 was no better and rolled more.
WEIGHT_ZONE = 0.5
UNSHIFT_SECONDS = 0.7
# A leg joint missing from a frame means "not seen", not "at stand". A knee
# raised toward the camera is dropped by the depth gate from ~75 deg up
# (the thigh looks too short on screen), and raised knees often fall below
# the knee-visibility threshold; reading either as "leg at stand" made the
# robot start a lift and put the foot straight back down. The last value
# actually seen is held for this long, then the leg is treated as at stand.
HOLD_MISSING_SECONDS = 4.0
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


def _new_reading() -> dict[str, float]:
    return {"frames": 0, "l_peak": 0.0, "r_peak": 0.0, "l_unseen": 0, "r_unseen": 0}


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
        self._cleared = False
        self._rising = False
        self._last_seen: dict[str, float] = {}
        self._unseen_for: dict[str, float] = {}
        self._lift_f = {"l": 0.0, "r": 0.0}
        self._dt = 0.0
        # Eased slide-back state: where the hips started from, and how far in.
        self._unshift_from: dict[str, float] | None = None
        self._unshift_t = 0.0
        self._cmd: dict[str, float] = {j: _stand(j) for j in LEG_JOINTS + ANKLES}
        self._reading = _new_reading()

    def take_reading(self) -> dict[str, float]:
        """What the camera reported for the legs since the last call: peak
        lift per leg (fraction of hip travel; a lift starts at LIFT_ON) and
        the share of frames each leg was not seen. For the follow log --
        without it, a lift that was never recognised cannot be diagnosed."""
        r, self._reading = self._reading, _new_reading()
        n = max(1, r.pop("frames"))
        return {k: round(v / n if k.endswith("unseen") else v, 3) for k, v in r.items()}

    def _slew(self, goals: dict[str, float], dt: float) -> None:
        unshifting = self.phase is Phase.UNSHIFTING
        for joint, goal in goals.items():
            rate = _rate(joint)
            if unshifting and joint in ANKLES + HIP_ROLLS:
                # Enough headroom to follow the eased curve, whose peak
                # slope is 1.5x the average.
                rate *= 1.5 * SHIFT_SECONDS / UNSHIFT_SECONDS
            step = rate * dt
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
        self._reading["frames"] += 1
        for s_ in ("l", "r"):
            if f"{s_}_hip_pitch" in desired:
                self._reading[f"{s_}_peak"] = max(
                    self._reading[f"{s_}_peak"], signed_lift(s_, desired))
            else:
                self._reading[f"{s_}_unseen"] += 1
        desired = self._fill_unseen_legs(desired, dt)
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
        swing_down = self.swing is not None and all(
            abs(self._cmd[j] - _stand(j)) <= _AT_GOAL
            for j in (f"{self.swing}_hip_pitch", f"{self.swing}_knee")
        )

        if self.phase is Phase.SHIFTING and self._at(goals, shift_joints):
            self.phase = Phase.LIFTING
        elif self.phase is Phase.LOWERING and swing_down:
            self.phase = Phase.UNSHIFTING
        elif (self.phase is Phase.UNSHIFTING and self._unshift_t >= UNSHIFT_SECONDS
              and self._at(goals, shift_joints)):
            self.phase, self.swing = Phase.IDLE, None

        if self.phase is not Phase.UNSHIFTING:
            self._unshift_from = None

        out = dict(desired)
        out.update(self._cmd)
        return out

    def _fill_unseen_legs(self, desired: dict[str, float], dt: float) -> dict[str, float]:
        """Substitute the last value actually seen for any leg joint missing
        from this frame, for up to HOLD_MISSING_SECONDS (see there)."""
        out = dict(desired)
        for j in LEG_JOINTS:
            if j in desired:
                self._last_seen[j] = desired[j]
                self._unseen_for[j] = 0.0
                continue
            self._unseen_for[j] = self._unseen_for.get(j, 0.0) + dt
            if j in self._last_seen and self._unseen_for[j] <= HOLD_MISSING_SECONDS:
                out[j] = self._last_seen[j]
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

    def _landing_weight_fraction(self) -> float:
        """How much of the weight shift to hold, 0..1, as the foot comes down.

        Full shift until the lifted foot has been clear of the floor and is
        now coming back into the last WEIGHT_ZONE; from there the hips
        ease back in step with the foot, so the weight is centred by the time
        the leg is straight.

        Traced falls in the live pipeline: the real foot touched the floor
        while the command was still in the slow final approach, and for the
        next ~0.6s the leg kept extending against the floor with the hips
        still shifted. Extending a planted leg pushes that side of the pelvis
        up; the robot tipped steadily (-0.7 -> -5.8 deg), and by the time a
        separate slide-back began, the landed foot was lifting off again and
        it rolled over. Moving the weight back WHILE landing removes that
        window. It stays safe on the way down: with the hips half back the
        centre of mass is still over the standing foot (13mm from its centre,
        foot half-width 25mm); it only reaches centre as the foot lands.
        """
        if not self._cleared or not self._held_swing or self._rising:
            # Rising: go for the full shift at once and let _supported_lift
            # make the foot wait for it. Coupling shift to foot height on the
            # way UP deadlocks -- the foot is capped by the shift, and the
            # shift only grows as the foot rises -- so a re-lift crept up.
            return 1.0
        joint = f"{self.swing}_hip_pitch"
        zone = WEIGHT_ZONE * _reach(joint)
        # Only a lowering the PERSON actually made counts: use the higher of
        # the commanded leg and the smoothed reading. A run of dropped frames
        # can pull the commanded leg into the final approach while the person
        # is still holding their leg up; moving the weight back then, on one
        # foot, leaned the robot +5 -> +14 deg and it fell on the next re-lift.
        seen = max(0.0, self._lift_f[self.swing]) * _reach(joint)
        height = max(self._held_swing.get(joint, 0.0), seen)
        p = min(1.0, height / zone)
        return p * p * (3.0 - 2.0 * p)

    def _supported_lift(self, joint: str) -> float:
        """Highest lift the foot may RISE to right now: unlimited once the
        weight shift is complete, otherwise nowhere (the caller then holds the
        foot where it already is -- this never pushes it down).

        Allowing height in proportion to a partial shift -- the landing curve
        run in reverse -- is safe coming down but on the way up it is shifting
        and lifting at the same time, which topples this robot; a re-lift
        straight after an un-shift fell that way under heavy dropout.
        """
        full = _shift(self.swing)["l_ank_roll"]
        progress = (self._cmd["l_ank_roll"] - _stand("l_ank_roll")) / full
        return float("inf") if progress >= 0.98 else 0.0

    def _goals(self, desired: dict[str, float]) -> dict[str, float]:
        idle_legs = limit_leg_travel(
            {j: desired.get(j, _stand(j)) for j in LEG_JOINTS}, IDLE_TRAVEL
        )
        if self.phase is Phase.IDLE:
            self._cleared = False
            return {**idle_legs, **{a: _stand(a) for a in ANKLES}}

        swing = self.swing
        support = "r" if swing == "l" else "l"
        if self.phase is Phase.UNSHIFTING:
            # Ease the hips back: start and finish at zero speed. A linear
            # slide-back begins with an abrupt change of speed, and the
            # trace showed the lean GROWING right as it began (-3.6 ->
            # -5.0 deg) before recovering.
            if self._unshift_from is None:
                self._unshift_from = {j: self._cmd[j] for j in ANKLES + HIP_ROLLS}
                self._unshift_t = 0.0
            self._unshift_t += self._dt
            p = min(1.0, self._unshift_t / UNSHIFT_SECONDS)
            eased = p * p * (3.0 - 2.0 * p)
            goals = {
                j: start + (_stand(j) - start) * eased
                for j, start in self._unshift_from.items()
            }
        else:
            offsets = _shift(swing)
            weight = self._landing_weight_fraction()
            goals = {j: _stand(j) + offsets[j] * weight for j in ANKLES + HIP_ROLLS}

        # The robot stands on the support leg; it holds its stance.
        for j in (f"{support}_hip_pitch", f"{support}_knee"):
            goals[j] = _stand(j)

        swing_joints = (f"{swing}_hip_pitch", f"{swing}_knee")
        if self.phase in (Phase.LIFTING, Phase.LOWERING):
            hip = f"{swing}_hip_pitch"
            limited = limit_leg_travel({hip: desired.get(hip, _stand(hip))}, LIFT_TRAVEL)
            held = {}
            for j in (hip,):
                if self.phase is Phase.LOWERING:
                    wanted = 0.0
                else:
                    wanted = abs(_lift_side_only(j, limited[j]) - _stand(j))
                previous = self._held_swing.get(j, 0.0) if self._held_swing else 0.0
                near_floor = previous <= TOUCHDOWN_ZONE * _reach(j)
                rate = TOUCHDOWN_RATE if near_floor else LOWER_RATE
                floor = previous - rate * _reach(j) * self._dt
                amount = max(wanted, floor, 0.0)
                # Never let the foot rise higher than the weight shift that is
                # actually in place supports. Otherwise, re-lifting while the
                # hips are sliding back from a landing (marching, quick
                # repeats) lifts the foot before the weight is across -- which
                # toppled the robot every time in a no-gap march. Only limits
                # upward movement; it never forces the foot down.
                ceiling = self._supported_lift(j)
                held[j] = min(amount, max(previous, ceiling))
                self._rising = self.phase is Phase.LIFTING and wanted > previous + 1e-3
            knee = f"{swing}_knee"
            held[knee] = min(KNEE_PER_HIP * held[hip], _reach(knee))
            self._held_swing = held
            if held[hip] > TOUCHDOWN_ZONE * _reach(hip):
                # Foot has been properly clear of the floor this lift, so the
                # way it comes back down counts as a landing. Never set on the
                # way up, where the weight must be fully across first.
                self._cleared = True
            for j, amount in held.items():
                goals[j] = _lift_side_only(j, _stand(j) + _lift_sign(j) * amount)
        elif self.phase is Phase.SHIFTING:
            self._held_swing = None
            self._cleared = False
            # Weight not across yet: foot fully planted, so the only thing
            # moving is the hip slide. Even a small unsupported lift here
            # leans the robot before the shift can catch it.
            goals.update({j: _stand(j) for j in swing_joints})
        else:  # UNSHIFTING -- foot already down; hold it at stand.
            goals.update({j: _stand(j) for j in swing_joints})
        return goals
