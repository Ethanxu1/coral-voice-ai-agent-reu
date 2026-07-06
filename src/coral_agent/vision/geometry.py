"""Torso-relative geometry for MediaPipe `pose_world_landmarks`.

Coordinate conventions used inside this module:
- World vectors come from MediaPipe `pose_world_landmarks` (meters, hip-centered).
  We treat the underlying axis directions as opaque; the torso frame is derived
  from the landmarks themselves, so axis conventions cancel out.
- Torso frame columns: x = person's left, y = up (hip→shoulder), z = forward
  (out of chest). Built right-handed via orthonormalization.
- Returned angles are in radians.
"""

from __future__ import annotations

import math
from typing import Literal, Optional

import numpy as np

# MediaPipe pose landmark indices used here
NOSE = 0
LEFT_EAR = 7
RIGHT_EAR = 8
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_ELBOW = 13
RIGHT_ELBOW = 14
LEFT_WRIST = 15
RIGHT_WRIST = 16
LEFT_PINKY = 17
RIGHT_PINKY = 18
LEFT_INDEX = 19
RIGHT_INDEX = 20
LEFT_HIP = 23
RIGHT_HIP = 24
LEFT_KNEE = 25
RIGHT_KNEE = 26
LEFT_ANKLE = 27
RIGHT_ANKLE = 28


def world_xyz(lm: dict) -> np.ndarray:
    """Pull (xw, yw, zw) from a body landmark dict as a float64 vector."""
    return np.array([lm["xw"], lm["yw"], lm["zw"]], dtype=np.float64)


def image_xy(lm: dict) -> np.ndarray:
    """Pull image-normalized (x, y) from a body landmark dict."""
    return np.array([lm["x"], lm["y"]], dtype=np.float64)


def torso_frame(
    l_sho_w: np.ndarray,
    r_sho_w: np.ndarray,
    l_hip_w: np.ndarray,
    r_hip_w: np.ndarray,
) -> np.ndarray:
    """Build a 3x3 rotation matrix whose columns are the torso axes in world.

    Axes (person-anatomical):
      column 0 (x): person's right → left (along shoulder line)
      column 1 (y): up (hip-mid → shoulder-mid)
      column 2 (z): forward (out of chest), via cross
    """
    shoulder_mid = 0.5 * (l_sho_w + r_sho_w)
    hip_mid = 0.5 * (l_hip_w + r_hip_w)

    x_raw = l_sho_w - r_sho_w
    y_raw = shoulder_mid - hip_mid

    x_axis = x_raw / (np.linalg.norm(x_raw) + 1e-9)
    y_axis = y_raw - np.dot(y_raw, x_axis) * x_axis
    y_axis = y_axis / (np.linalg.norm(y_axis) + 1e-9)
    z_axis = np.cross(x_axis, y_axis)
    return np.column_stack([x_axis, y_axis, z_axis])


def to_torso(v_world: np.ndarray, R_torso: np.ndarray) -> np.ndarray:
    """Express a world-frame vector in the torso frame."""
    return R_torso.T @ v_world


def pelvis_frame(
    l_hip_w: np.ndarray,
    r_hip_w: np.ndarray,
    up_hint_w: np.ndarray,
) -> Optional[np.ndarray]:
    """Build a 3x3 rotation matrix whose columns are the pelvis axes in world.

    Unlike torso_frame, the up axis comes from `up_hint_w` (the caller's
    world-up, e.g. gravity) rather than the hip→shoulder line. This decouples
    leg retargeting from torso lean: bending forward at the waist doesn't
    register as the legs swinging. The trade-off is an explicit dependency on
    the caller knowing the world's up direction (for MediaPipe world landmarks
    that's -Y, determined empirically — Google doesn't document it), and an
    assumption that the camera is roughly level.

    Axes (person-anatomical, mirroring torso_frame's column convention):
      column 0 (x): person's right → left (along hip line)
      column 1 (y): up (gravity, from up_hint_w)
      column 2 (z): forward (out of pelvis), via cross

    Returns None when the hip line is too close to vertical (person lying
    down / extreme camera angle) — the frame is degenerate and legs shouldn't
    be retargeted from it.
    """
    x_raw = l_hip_w - r_hip_w
    x_axis = x_raw / (np.linalg.norm(x_raw) + 1e-9)

    up = up_hint_w / (np.linalg.norm(up_hint_w) + 1e-9)
    y_axis = up - np.dot(up, x_axis) * x_axis
    y_norm = float(np.linalg.norm(y_axis))
    # sqrt(1 - (x·up)^2) < 0.3 ⇔ hip line within ~17° of vertical
    if y_norm < 0.3:
        return None
    y_axis = y_axis / y_norm
    z_axis = np.cross(x_axis, y_axis)
    return np.column_stack([x_axis, y_axis, z_axis])


def shoulder_pitch_roll(
    shoulder_w: np.ndarray,
    elbow_w: np.ndarray,
    R_torso: np.ndarray,
    side: Literal["left", "right"],
) -> tuple[float, float]:
    """Return (pitch, roll_abduction) for one shoulder, both in radians, both >= 0
    for the natural forward / outward motion.

    pitch:        0 = arm hanging down, +π/2 = arm forward, +π = overhead.
    roll_abduct:  0 = arm hanging at side, +π/2 = arm horizontal out to side.

    `side` indicates which arm: roll sign flips because abduction is "+left" for
    the left arm and "+right" (i.e. -x_torso) for the right arm.
    """
    arm = elbow_w - shoulder_w
    arm_t = to_torso(arm, R_torso)
    n = float(np.linalg.norm(arm_t))
    if n < 1e-6:
        return 0.0, 0.0
    v = arm_t / n

    # Sagittal plane (y-z): pitch = atan2(forward, -down).
    # When the arm is purely lateral (T-pose), the sagittal projection is zero
    # and pitch is geometrically undefined; pick 0 by convention to keep pitch
    # decoupled from roll.
    sagittal = math.hypot(float(v[1]), float(v[2]))
    if sagittal < 1e-6:
        pitch = 0.0
    else:
        pitch = math.atan2(float(v[2]), -float(v[1]))

    # Lateral component: clamp asin input to [-1, 1] for numerical safety
    lateral = float(v[0]) if side == "left" else -float(v[0])
    lateral = max(-1.0, min(1.0, lateral))
    roll_abd = math.asin(lateral)
    return pitch, roll_abd


def elbow_bend(
    shoulder_w: np.ndarray,
    elbow_w: np.ndarray,
    wrist_w: np.ndarray,
) -> float:
    """Unsigned flexion angle between upper arm and forearm, in [0, π]."""
    upper = elbow_w - shoulder_w
    forearm = wrist_w - elbow_w
    nu = float(np.linalg.norm(upper))
    nf = float(np.linalg.norm(forearm))
    if nu < 1e-4 or nf < 1e-4:
        return 0.0
    cos_a = float(np.dot(upper, forearm)) / (nu * nf)
    cos_a = max(-1.0, min(1.0, cos_a))
    return math.acos(cos_a)


def hip_pitch_roll(
    hip_w: np.ndarray,
    knee_w: np.ndarray,
    R_pelvis: np.ndarray,
    side: Literal["left", "right"],
) -> tuple[float, float]:
    """Return (pitch, roll_abduction) for one hip, both in radians.

    Same decomposition as shoulder_pitch_roll — the hip→knee vector plays the
    role of the shoulder→elbow vector, expressed in the pelvis frame instead
    of the torso frame:

    pitch:        0 = leg hanging down, +π/2 = thigh forward (hip flexion),
                  negative = leg behind the body (hip extension).
    roll_abduct:  0 = leg straight down, positive = leg out to the side
                  (abduction), negative = crossed inward (adduction).
    """
    return shoulder_pitch_roll(hip_w, knee_w, R_pelvis, side)


def knee_bend(
    hip_w: np.ndarray,
    knee_w: np.ndarray,
    ankle_w: np.ndarray,
) -> float:
    """Unsigned knee flexion between thigh and shank, in [0, π]. 0 = straight.

    Same segment-angle math as elbow_bend (thigh ↔ upper arm, shank ↔ forearm);
    frame-independent, so it needs no pelvis frame.
    """
    return elbow_bend(hip_w, knee_w, ankle_w)


def forearm_twist(
    elbow_w: np.ndarray,
    wrist_w: np.ndarray,
    index_w: np.ndarray,
    pinky_w: np.ndarray,
    R_torso: np.ndarray,
    side: Literal["left", "right"],
) -> Optional[float]:
    """Signed forearm pronation/supination, in radians.

    The forearm axis is wrist→elbow→wrist; the hand's palm-across direction is
    given by BlazePose's pinky→index landmark pair. We project that vector into
    the plane perpendicular to the forearm axis and measure its signed angle
    from torso-up (the reference that makes the natural arm-hanging "palm
    inward" pose come out close to zero on both sides).

    Returns None when the geometry is degenerate (forearm zero-length, hand
    landmarks coincident, or forearm aligned with both torso-up and
    torso-forward).
    """
    forearm = wrist_w - elbow_w
    f_norm = float(np.linalg.norm(forearm))
    if f_norm < 1e-4:
        return None
    f = forearm / f_norm

    # Palm-across vector: pinky_mcp → index_mcp, projected perp to forearm.
    palm_across = index_w - pinky_w
    if float(np.linalg.norm(palm_across)) < 1e-4:
        return None
    p_perp = palm_across - np.dot(palm_across, f) * f
    p_norm = float(np.linalg.norm(p_perp))
    if p_norm < 1e-4:
        return None
    p_perp = p_perp / p_norm

    # Reference: torso-up projected perp to forearm. Falls back to torso-forward
    # for arm-overhead poses where torso-up is parallel to the forearm.
    for axis_col in (1, 2):
        ref = R_torso[:, axis_col]
        ref_perp = ref - np.dot(ref, f) * f
        r_norm = float(np.linalg.norm(ref_perp))
        if r_norm >= 1e-3:
            ref_perp = ref_perp / r_norm
            break
    else:
        return None

    cos_a = float(np.dot(ref_perp, p_perp))
    cos_a = max(-1.0, min(1.0, cos_a))
    sin_a = float(np.dot(np.cross(ref_perp, p_perp), f))
    angle = math.atan2(sin_a, cos_a)

    # Mirror the right arm so positive twist always corresponds to the same
    # anatomical sense (supination / "rotate out") for both sides.
    if side == "right":
        angle = -angle
    return angle


def head_pan_tilt_roll(
    nose_w: np.ndarray,
    l_ear_w: np.ndarray,
    r_ear_w: np.ndarray,
    R_torso: np.ndarray,
) -> tuple[float, float, float]:
    """Compute torso-relative head pan/tilt/roll from world landmarks (radians).

    pan:  0 forward, > 0 turned to person's right (matches existing "head right
          = positive head_pan" convention in validation.py).
    tilt: 0 horizontal, > 0 looking up.
    roll: 0 level, > 0 tilted to person's right (left ear up).
    """
    head_forward = nose_w - 0.5 * (l_ear_w + r_ear_w)
    ear_line = l_ear_w - r_ear_w
    fn = float(np.linalg.norm(head_forward))
    en = float(np.linalg.norm(ear_line))
    if fn < 1e-6 or en < 1e-6:
        return 0.0, 0.0, 0.0
    fwd_t = to_torso(head_forward / fn, R_torso)
    ear_t = to_torso(ear_line / en, R_torso)
    pan = math.atan2(-float(fwd_t[0]), float(fwd_t[2]))
    horiz = math.hypot(float(fwd_t[0]), float(fwd_t[2]))
    tilt = math.atan2(float(fwd_t[1]), horiz)
    roll = math.atan2(float(ear_t[1]), float(ear_t[0]))
    return pan, tilt, roll


def arm_image_projection_short(
    shoulder_img: np.ndarray,
    elbow_img: np.ndarray,
    threshold: float = 0.05,
) -> bool:
    """Depth-ambiguity gate: True if shoulder→elbow 2D projection is short
    relative to the frame, meaning the arm points roughly along the camera
    optical axis and depth estimates become unreliable.

    Inputs are normalized image coords in [0, 1]; the default threshold of
    0.05 corresponds to ~5% of frame size, roughly within 15° of optical axis
    for a typical upper-arm length.
    """
    return float(np.linalg.norm(elbow_img - shoulder_img)) < threshold
