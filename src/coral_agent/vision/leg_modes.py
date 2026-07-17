"""Selectable leg-retargeting strategies for the sim demo's /map-features.

Three modes, chosen per request:

  "retarget"  (default) — the current pelvis-frame leg retargeting in
                pose_to_robot.compute_joint_targets. Nothing here; the caller
                just uses compute_joint_targets unchanged.

  "legacy"    — a faithful port of the old pose_mimic_3d.compute_leg_pulses:
                drives hip_yaw (11/12) from forward/backward thigh swing and
                hip_roll (9/10) from lateral tilt, via atan2 on raw MediaPipe
                world axes. This is the ANATOMICALLY WRONG mapping documented
                in that node (sagittal swing sent to the yaw joint), preserved
                on purpose so the two behaviours can be compared side by side.

  "classify"  — run the MobileNetV3 pose classifier, then take ALL leg servos
                (IDs 1-12) from the matching canned pose in robot.motions. The
                legs snap to that class's stance; the arms keep the live
                retargeting.

  "buckets"   — classify the person's leg pose into a small set of discrete
                stances rather than continuously retargeting. See the "Mode 4"
                section below.

Modes 2 and 3 are authored in *hardware* servo pulses (the units the old node
and motions.py use). This module converts those pulses back to sim radians with
hardware_units_to_rad — exactly how server._play_sim_motion renders canned poses
in the sim — so the values land at the right MuJoCo angles despite the joints
whose hardware neutral isn't 500 (hip_pitch, ankles). The caller then runs the
merged radian dict through targets_to_servo_commands like any other frame.
"""

from __future__ import annotations

import math
from typing import Dict, Literal, Optional

import numpy as np

from coral_agent.robot.hardware_angle_utils import hardware_units_to_rad
from coral_agent.robot.servo_config import STAND_PULSE

from . import geometry

LegMode = Literal["retarget", "legacy", "classify", "buckets"]
LEG_MODES: tuple[str, ...] = ("retarget", "legacy", "classify", "buckets")

# The 12 leg joints (servo IDs 1-12). Used both to strip pelvis-frame legs out
# of a compute_joint_targets result and to pull leg servos from a canned pose.
LEG_JOINTS: tuple[str, ...] = (
    "l_ank_roll", "r_ank_roll",
    "l_ank_pitch", "r_ank_pitch",
    "l_knee", "r_knee",
    "l_hip_pitch", "r_hip_pitch",
    "l_hip_roll", "r_hip_roll",
    "l_hip_yaw", "r_hip_yaw",
)

# ── Class → canned pose (mode 3) ────────────────────────────────────────────
# The 7 classifier labels each name a single-frame pose in robot.motions with
# the same key. Resolved lazily so importing this module stays torch-free.
_CLASS_TO_MOTION = {
    "dab": "dab",
    "hand-raised": "hand-raised",
    "muscles": "muscles",
    "superhero": "superhero",
    "t-pose": "t-pose",
    "thinker": "thinker",
    "warrior2": "warrior2",
}


def strip_legs(targets: Dict[str, float]) -> Dict[str, float]:
    """Return `targets` without any leg joints (keeps arms + head)."""
    return {k: v for k, v in targets.items() if k not in LEG_JOINTS}


def stand_leg_targets() -> Dict[str, float]:
    """Sim-radian targets that put ALL 12 leg joints in the stand pose.

    Built from each joint's STAND_PULSE via the same hardware→sim conversion the
    other modes use, so the legs land exactly at the ainex.xml stand keyframe.
    Used to straighten the legs mode-independently (retarget/legacy/classify all
    share it) when the knees aren't confidently visible, instead of driving them
    off unreliable landmarks or holding a stale pose.
    """
    return leg_pulses_to_targets({j: STAND_PULSE[j] for j in LEG_JOINTS})


def leg_pulses_to_targets(leg_pulses: Dict[str, int]) -> Dict[str, float]:
    """Convert a {leg_joint: hardware_pulse} dict to {leg_joint: sim_radians}.

    Inverts each joint's hardware calibration (stand-pulse anchor + mirror-mount
    direction) so a pose authored in hardware units renders at the right sim
    angle — the same conversion server._play_sim_motion uses for canned motions.
    """
    return {
        joint: hardware_units_to_rad(int(pulse), joint)
        for joint, pulse in leg_pulses.items()
        if joint in LEG_JOINTS
    }


# ── Mode 2: legacy atan2 leg pulses ─────────────────────────────────────────
_UNITS_PER_DEG = 1000.0 / 240.0  # ≈ 4.17, matches the old node


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def legacy_leg_pulses(body_landmarks: list[dict]) -> Dict[str, int]:
    """Port of pose_mimic_3d.compute_leg_pulses — the deliberately-wrong mapping.

    Drives only hip_yaw (11/12) from sagittal swing and hip_roll (9/10) from
    lateral tilt; every other leg servo is held at its stand pulse. Returns all
    12 leg joints so the stance is fully specified. Falls back to a full stand
    stance if the hip/knee world landmarks aren't available.

    Landmark world coords come straight from the dicts (xw/yw/zw); the axis
    assumptions (Y-down, +Z toward the person's back) and the flipped-image
    left/right identity are inherited verbatim from the old node.
    """
    pulses: Dict[str, int] = {j: STAND_PULSE[j] for j in LEG_JOINTS}

    def _world(i: int):
        lm = body_landmarks[i] if i < len(body_landmarks) else None
        if not lm or "xw" not in lm:
            return None
        return np.array([lm["xw"], lm["yw"], lm["zw"]], dtype=np.float64)

    l_hip = _world(geometry.LEFT_HIP)
    r_hip = _world(geometry.RIGHT_HIP)
    l_knee = _world(geometry.LEFT_KNEE)
    r_knee = _world(geometry.RIGHT_KNEE)
    if any(v is None for v in (l_hip, r_hip, l_knee, r_knee)):
        return pulses

    l_upper_leg = l_knee - l_hip
    r_upper_leg = r_knee - r_hip

    # Hip yaw (servo 11/12): forward/backward leg swing — atan2(-Z, Y).
    l_yaw = math.degrees(math.atan2(-l_upper_leg[2], l_upper_leg[1]))
    r_yaw = math.degrees(math.atan2(-r_upper_leg[2], r_upper_leg[1]))
    l_yaw = _clamp(l_yaw, -20, 45)
    r_yaw = _clamp(r_yaw, -20, 45)
    pulses["l_hip_yaw"] = int(_clamp(STAND_PULSE["l_hip_yaw"] - l_yaw * _UNITS_PER_DEG, 300, 600))
    pulses["r_hip_yaw"] = int(_clamp(STAND_PULSE["r_hip_yaw"] + r_yaw * _UNITS_PER_DEG, 400, 700))

    # Hip roll (servo 9/10): lateral leg tilt — atan2(X, Y).
    l_roll = math.degrees(math.atan2(l_upper_leg[0], l_upper_leg[1]))
    r_roll = math.degrees(math.atan2(r_upper_leg[0], r_upper_leg[1]))
    l_roll = _clamp(l_roll, -30, 20)
    r_roll = _clamp(r_roll, -20, 30)
    pulses["l_hip_roll"] = int(_clamp(STAND_PULSE["l_hip_roll"] + l_roll * _UNITS_PER_DEG, 400, 600))
    pulses["r_hip_roll"] = int(_clamp(STAND_PULSE["r_hip_roll"] + r_roll * _UNITS_PER_DEG, 400, 600))

    return pulses


# ── Mode 3: classified canned-pose leg pulses ───────────────────────────────
def classify_leg_pulses(class_name: str) -> Dict[str, int]:
    """Return the 12 leg-servo hardware pulses from the canned pose for
    `class_name`. Unknown class → full stand stance (safe no-op)."""
    from coral_agent.robot import motions

    motion_name = _CLASS_TO_MOTION.get(class_name)
    if motion_name is None:
        return {j: STAND_PULSE[j] for j in LEG_JOINTS}
    sequence = motions.get_motion(motion_name)
    if not sequence:
        return {j: STAND_PULSE[j] for j in LEG_JOINTS}
    pose = sequence[0][0]  # single-frame pose: (pulse_dict, duration)
    return {j: int(pose.get(j, STAND_PULSE[j])) for j in LEG_JOINTS}


# ── Mode 4: bucketed leg stances ────────────────────────────────────────────
#
# Instead of continuously retargeting, classify the person's legs into a small
# set of discrete stances and snap straight to a fixed, pre-authored target for
# whichever bucket wins. Three independent bucket decisions are made per capture
# — knee/ankle/hip-pitch bend depth (both legs together), LEFT hip yaw, and
# RIGHT hip yaw (each leg independently) — for 3 x 3 x 3 = 27 possible
# combinations. hip_roll and ank_roll are never driven by a bucket and always
# sit at stand (see stand_leg_targets baseline below).
#
# Knee/ankle/hip-pitch bucket ("low"/"stand"/"high") — measures knee bend depth
# via geometry.knee_bend(hip_w, knee_w, ankle_w): the unsigned angle (0-180)
# between the upper-leg vector (hip->knee) and the lower-leg vector
# (knee->ankle), same world-coordinate computation "retarget" mode already uses
# to drive the continuous knee target (geometry.knee_bend is frame-independent —
# it does NOT use the pelvis frame/plane that retarget's hip_pitch/roll do).
# Averaged across both legs (unlike hip yaw below, this stays a single combined
# decision — the left/right target tables are still pre-mirrored per bucket),
# then bucketed:
#   < 30deg  -> "low"   (deep knee bend / crouch — knee, ankle, AND hip pitch
#                        all deepen together)
#   30-65deg -> "stand"
#   > 65deg  -> "high"  (straighter legs / taller stance)
# hip_pitch is driven by this SAME bucket decision (not a separate one) — each
# bucket's target table sets knee + ank_pitch + hip_pitch together so the whole
# leg deepens or straightens as one stance, rather than hip flexion moving
# independently of how bent the knee is.
#
# Hip-yaw bucket ("in"/"stand"/"out") — hip yaw can't be recovered from the 3D
# hip->knee vector alone (see compute_joint_targets' module docstring), so this
# uses a 2D heuristic off the camera image: the knee's HORIZONTAL position
# relative to the same-side hip and shoulder. "Outward" is the image-x direction
# pointing from the body midline (the two hips' midpoint) toward this leg's hip;
# comparing the knee's outwardness against the hip's and shoulder's:
#   knee at hip or inward of it       -> "in"
#   knee between the hip and shoulder  -> "stand"
#   knee outward of the shoulder       -> "out"
# Computed independently per leg (each uses only its own hip/knee/shoulder, plus
# both hips to fix the outward direction) — one leg can land "in" while the
# other is "out".
_VIS_THRESHOLD = 0.5

# Per-side hip yaw targets — independent lookups now (not a paired dict), since
# each leg is classified on its own.
_HIP_YAW_L_TARGETS: Dict[str, float] = {"in": 0.05, "stand": 0.00, "out": -0.30}
_HIP_YAW_R_TARGETS: Dict[str, float] = {"in": -0.05, "stand": 0.00, "out": 0.30}

_KNEE_ANKLE_BUCKET_TARGETS: Dict[str, Dict[str, float]] = {
    "high":  {"l_knee": 0.73, "r_knee": -0.73, "l_ank_pitch": 0.25, "r_ank_pitch": -0.25,
              "l_hip_pitch": -0.489, "r_hip_pitch": 0.489},
    "stand": {"l_knee": 0.925, "r_knee": -0.925, "l_ank_pitch": 0.454, "r_ank_pitch": -0.454,
              "l_hip_pitch": -0.489, "r_hip_pitch": 0.489},
    "low":   {"l_knee": 1.553, "r_knee": -1.553, "l_ank_pitch": 0.789, "r_ank_pitch": -0.789,
              "l_hip_pitch": -0.929, "r_hip_pitch": 0.929},
}

# Public bucket-name tuples, for callers (e.g. leg_bucket_test.py) that need to
# enumerate every combination without reaching into the target tables above.
HIP_YAW_BUCKETS: tuple[str, ...] = ("in", "stand", "out")
KNEE_ANKLE_BUCKETS: tuple[str, ...] = tuple(_KNEE_ANKLE_BUCKET_TARGETS.keys())


def _lm(body: list[dict], idx: int) -> dict | None:
    if idx >= len(body):
        return None
    lm = body[idx]
    if lm.get("visibility", 0.0) < _VIS_THRESHOLD:
        return None
    return lm


def _lm_world(body: list[dict], idx: int) -> dict | None:
    lm = _lm(body, idx)
    if lm is None or "xw" not in lm:
        return None
    return lm


def knee_ankle_legs_visible(body_landmarks: list[dict]) -> bool:
    """True when both hips, knees, and ankles (world coords) clear the
    visibility gate — everything the (combined, both-legs) knee/ankle bucket
    needs. Below this, the knee/ankle bucket falls back to "stand"."""
    needed = (
        geometry.LEFT_HIP, geometry.RIGHT_HIP,
        geometry.LEFT_KNEE, geometry.RIGHT_KNEE,
        geometry.LEFT_ANKLE, geometry.RIGHT_ANKLE,
    )
    return all(_lm_world(body_landmarks, i) is not None for i in needed)


def _hip_yaw_side_visible(body_landmarks: list[dict], side: str) -> bool:
    """True when the given side's hip, knee, and shoulder (image coords)
    clear the visibility gate."""
    idxs = (
        (geometry.LEFT_HIP, geometry.LEFT_KNEE, geometry.LEFT_SHOULDER)
        if side == "left"
        else (geometry.RIGHT_HIP, geometry.RIGHT_KNEE, geometry.RIGHT_SHOULDER)
    )
    return all(_lm(body_landmarks, i) is not None for i in idxs)


def hip_yaw_visible(body_landmarks: list[dict]) -> bool:
    """True when BOTH sides' hip/knee/shoulder are visible.

    Even though the two hip-yaw buckets are classified independently (one leg
    can land "in" while the other is "out"), visibility is gated together: if
    EITHER side is occluded, BOTH hip yaws fall back to "stand" rather than
    only the occluded side — a half-good reading isn't trusted enough to drive
    just one leg while leaving the other unclassified relative to it."""
    return _hip_yaw_side_visible(body_landmarks, "left") and _hip_yaw_side_visible(body_landmarks, "right")


def _knee_ankle_bucket_from_avg_deg(avg_deg: float) -> str:
    """Bucket the both-legs-averaged 3D knee-bend angle into low/stand/high."""
    if avg_deg < 30.0:
        return "high"
    if avg_deg <= 65.0:
        return "stand"
    return "low"


def _knee_ankle_bucket(body: list[dict]) -> str:
    l_deg = math.degrees(geometry.knee_bend(
        geometry.world_xyz(body[geometry.LEFT_HIP]),
        geometry.world_xyz(body[geometry.LEFT_KNEE]),
        geometry.world_xyz(body[geometry.LEFT_ANKLE]),
    ))
    r_deg = math.degrees(geometry.knee_bend(
        geometry.world_xyz(body[geometry.RIGHT_HIP]),
        geometry.world_xyz(body[geometry.RIGHT_KNEE]),
        geometry.world_xyz(body[geometry.RIGHT_ANKLE]),
    ))
    return _knee_ankle_bucket_from_avg_deg(0.5 * (l_deg + r_deg))


def _hip_yaw_side_indices(side: str) -> tuple[int, int, int, int]:
    """(hip, knee, shoulder, other-hip) landmark indices for a side."""
    if side == "left":
        return geometry.LEFT_HIP, geometry.LEFT_KNEE, geometry.LEFT_SHOULDER, geometry.RIGHT_HIP
    return geometry.RIGHT_HIP, geometry.RIGHT_KNEE, geometry.RIGHT_SHOULDER, geometry.LEFT_HIP


def _hip_yaw_bucket_side(body: list[dict], side: str) -> str:
    """Classify a leg's hip yaw from the knee's horizontal (image-x) position
    relative to the same-side hip and shoulder. See the Mode 4 comment block."""
    hip_i, knee_i, sho_i, other_hip_i = _hip_yaw_side_indices(side)
    hip_x = body[hip_i]["x"]
    knee_x = body[knee_i]["x"]
    sho_x = body[sho_i]["x"]
    other_hip_x = body[other_hip_i]["x"]

    # "Outward" is the image-x direction from the body midline toward this hip.
    # Multiplying every x by this sign turns raw x into signed "outwardness"
    # (larger = further out) while preserving the comparisons below.
    outward = 1.0 if hip_x >= other_hip_x else -1.0
    knee_out = knee_x * outward
    hip_out = hip_x * outward
    sho_out = sho_x * outward

    if knee_out <= hip_out:   # knee at the hip or inward of it
        return "in"
    if knee_out <= sho_out:   # knee between the hip and shoulder
        return "stand"
    return "out"              # knee outward of the shoulder


def combine_bucket_targets(
    knee_ankle_bucket: str, hip_yaw_l_bucket: str, hip_yaw_r_bucket: str
) -> Dict[str, float]:
    """Build the full 12-joint leg target dict for an explicit bucket triple.

    Exposed separately from bucket_leg_targets() so a test harness can enumerate
    all 27 (knee_ankle x hip_yaw_l x hip_yaw_r) combinations without needing
    camera landmarks.
    """
    targets = stand_leg_targets()  # baseline: hip_roll/ank_roll stay stand
    # knee_ankle_bucket's target table below also sets hip_pitch, overriding
    # the stand baseline for it — see the Mode 4 comment block above.
    targets["l_hip_yaw"] = _HIP_YAW_L_TARGETS[hip_yaw_l_bucket]
    targets["r_hip_yaw"] = _HIP_YAW_R_TARGETS[hip_yaw_r_bucket]
    targets.update(_KNEE_ANKLE_BUCKET_TARGETS[knee_ankle_bucket])
    return targets


def classify_buckets(body_landmarks: list[dict]) -> tuple[str, str, str]:
    """Return (knee_ankle_bucket, hip_yaw_l_bucket, hip_yaw_r_bucket).

    The knee/ankle bucket and the hip-yaw pair are gated independently of each
    other: knee/ankle falls back to "stand" if its own (both-legs) landmarks
    aren't visible, regardless of hip-yaw visibility. Hip yaw's two buckets are
    classified independently of EACH OTHER when visible (see hip_yaw_visible) —
    one leg can land "in" while the other is "out" — but their visibility gate
    is shared: if either side is occluded, BOTH hip yaws fall back to "stand"
    together, not just the occluded one. Never returns None: full occlusion
    just means every component independently resolves to "stand".
    """
    knee_ankle = _knee_ankle_bucket(body_landmarks) if knee_ankle_legs_visible(body_landmarks) else "stand"
    if hip_yaw_visible(body_landmarks):
        hip_yaw_l = _hip_yaw_bucket_side(body_landmarks, "left")
        hip_yaw_r = _hip_yaw_bucket_side(body_landmarks, "right")
    else:
        hip_yaw_l = hip_yaw_r = "stand"
    return knee_ankle, hip_yaw_l, hip_yaw_r


def raw_bucket_readouts(body_landmarks: list[dict]) -> Dict[str, object]:
    """Return the raw quantities the bucket classifiers use, ungated by the
    shared visibility gates — for on-frame debug annotation, not for driving
    the robot. Values are None when the needed landmarks are out of range (or,
    for the knee angles, missing world coords).

    knee_bend_l/r_deg (float|None): 3D angle (geometry.knee_bend) between the
    upper-leg (hip->knee) and lower-leg (knee->ankle) vectors — the quantity
    _knee_ankle_bucket averages and buckets into low/stand/high.

    hip_yaw_l/r_bucket (str|None): the per-side "in"/"stand"/"out" bucket from
    the knee's horizontal position (_hip_yaw_bucket_side). Not an angle anymore
    (the hip-yaw method is now positional), so the readout is the bucket label
    the overlay draws against the hip/shoulder boundary posts.
    """
    def knee_deg(hip_i: int, knee_i: int, ankle_i: int) -> Optional[float]:
        if any(idx >= len(body_landmarks) for idx in (hip_i, knee_i, ankle_i)):
            return None
        if any("xw" not in body_landmarks[idx] for idx in (hip_i, knee_i, ankle_i)):
            return None
        return math.degrees(geometry.knee_bend(
            geometry.world_xyz(body_landmarks[hip_i]),
            geometry.world_xyz(body_landmarks[knee_i]),
            geometry.world_xyz(body_landmarks[ankle_i]),
        ))

    def yaw_bucket(side: str) -> Optional[str]:
        if any(idx >= len(body_landmarks) for idx in _hip_yaw_side_indices(side)):
            return None
        return _hip_yaw_bucket_side(body_landmarks, side)

    return {
        "knee_bend_l_deg": knee_deg(geometry.LEFT_HIP, geometry.LEFT_KNEE, geometry.LEFT_ANKLE),
        "knee_bend_r_deg": knee_deg(geometry.RIGHT_HIP, geometry.RIGHT_KNEE, geometry.RIGHT_ANKLE),
        "hip_yaw_l_bucket": yaw_bucket("left"),
        "hip_yaw_r_bucket": yaw_bucket("right"),
    }


def bucket_leg_targets(body_landmarks: list[dict]) -> Dict[str, float]:
    """Classify the person's legs into discrete stances and return sim-radian
    targets for all 12 leg joints (already the caller's target frame — unlike
    legacy_leg_pulses/classify_leg_pulses this returns targets directly, not
    hardware pulses, since the bucket tables above are authored in sim radians).

    See classify_buckets for the per-component visibility fallback.
    """
    knee_ankle, hip_yaw_l, hip_yaw_r = classify_buckets(body_landmarks)
    return combine_bucket_targets(knee_ankle, hip_yaw_l, hip_yaw_r)
