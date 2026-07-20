"""Tests for the selectable leg-retargeting strategies (leg_modes.py).

Covers the three building blocks the /map-features endpoint composes:
  - strip_legs / leg_pulses_to_targets (shared plumbing)
  - legacy_leg_pulses (mode 2: the deliberately-wrong atan2 mapping)
  - classify_leg_pulses (mode 3: canned pose lookup by class)
"""

from __future__ import annotations

import math

import pytest

from robot import motions
from robot.hardware_angle_utils import hardware_units_to_rad
from robot.servo_config import STAND_PULSE
from vision import leg_modes


def _empty_landmark() -> dict:
    return {"x": 0.5, "y": 0.5, "z": 0.0, "visibility": 1.0,
            "xw": 0.0, "yw": 0.0, "zw": 0.0}


def _body_with_legs(l_knee, r_knee, l_hip=(+0.1, 0.0, 0.0), r_hip=(-0.1, 0.0, 0.0)) -> list[dict]:
    body = [_empty_landmark() for _ in range(33)]

    def set_w(i, w):
        body[i]["xw"], body[i]["yw"], body[i]["zw"] = w

    set_w(leg_modes.geometry.LEFT_HIP, l_hip)
    set_w(leg_modes.geometry.RIGHT_HIP, r_hip)
    set_w(leg_modes.geometry.LEFT_KNEE, l_knee)
    set_w(leg_modes.geometry.RIGHT_KNEE, r_knee)
    return body


# ── strip_legs / leg_pulses_to_targets ──────────────────────────────────────


def test_strip_legs_keeps_arms_and_head():
    targets = {
        "l_sho_pitch": 0.1, "r_el_yaw": -0.2, "head_pan": 0.3,
        "l_hip_pitch": 0.4, "r_knee": -0.5, "l_hip_yaw": 0.6,
    }
    out = leg_modes.strip_legs(targets)
    assert set(out) == {"l_sho_pitch", "r_el_yaw", "head_pan"}


def test_leg_pulses_to_targets_stand_maps_to_calibrated_anchor():
    """Stand pulses invert to the calibrated stand radians (HW_STAND_RAD) — not
    necessarily 0, since the stand is a bent-knee stance after calibration."""
    from robot.hardware_angle_utils import HW_STAND_RAD

    stand = {j: STAND_PULSE[j] for j in leg_modes.LEG_JOINTS}
    targets = leg_modes.leg_pulses_to_targets(stand)
    assert set(targets) == set(leg_modes.LEG_JOINTS)
    for joint in leg_modes.LEG_JOINTS:
        assert targets[joint] == pytest.approx(HW_STAND_RAD.get(joint, 0.0), abs=1e-9), joint


def test_classify_leg_targets_within_joint_limits():
    """JOINT_LIMITS is now DERIVED from HW_SERVO_LIMITS (the hardware pulse
    ranges), and the canned classify poses were authored inside those ranges —
    so their leg targets must fall within the sim limits. Guards the sim ==
    hardware clamp agreement: a canned pose exceeding a sim limit means the
    two tables have drifted apart again."""
    from validation import JOINT_LIMITS

    targets = leg_modes.leg_pulses_to_targets(leg_modes.classify_leg_pulses("dab"))
    exceeded = [
        j for j, rad in targets.items()
        if j in JOINT_LIMITS and not JOINT_LIMITS[j].is_valid(rad)
    ]
    assert not exceeded, f"dab's leg targets exceed the hardware-derived sim limits: {exceeded}"


def test_leg_pulses_to_targets_matches_hardware_inverse():
    pulses = {"l_hip_yaw": 300, "r_hip_yaw": 700}
    targets = leg_modes.leg_pulses_to_targets(pulses)
    assert targets["l_hip_yaw"] == pytest.approx(hardware_units_to_rad(300, "l_hip_yaw"))
    assert targets["r_hip_yaw"] == pytest.approx(hardware_units_to_rad(700, "r_hip_yaw"))


def test_leg_pulses_to_targets_ignores_non_leg_joints():
    out = leg_modes.leg_pulses_to_targets({"l_sho_pitch": 500, "l_hip_yaw": 500})
    assert "l_sho_pitch" not in out
    assert "l_hip_yaw" in out


# ── Mode 2: legacy atan2 ─────────────────────────────────────────────────────


def test_legacy_standing_holds_all_at_stand():
    """Legs straight down → hip yaw/roll at stand pulse (500), all 12 present."""
    body = _body_with_legs(l_knee=(+0.1, 0.4, 0.0), r_knee=(-0.1, 0.4, 0.0))
    pulses = leg_modes.legacy_leg_pulses(body)
    assert set(pulses) == set(leg_modes.LEG_JOINTS)
    assert pulses["l_hip_yaw"] == pytest.approx(500, abs=1)
    assert pulses["r_hip_yaw"] == pytest.approx(500, abs=1)
    assert pulses["l_hip_roll"] == pytest.approx(500, abs=1)
    # Untouched joints held exactly at stand
    assert pulses["l_knee"] == STAND_PULSE["l_knee"]
    assert pulses["l_hip_pitch"] == STAND_PULSE["l_hip_pitch"]


def test_legacy_thigh_forward_drives_hip_yaw_not_pitch():
    """The wrong-on-purpose mapping: a forward thigh swing moves hip_YAW, and
    hip_pitch stays at stand. (Forward = -z in MediaPipe world.)"""
    dz = -0.4 * math.sin(math.radians(30))
    dy = 0.4 * math.cos(math.radians(30))
    body = _body_with_legs(l_knee=(+0.1, dy, dz), r_knee=(-0.1, 0.4, 0.0))
    pulses = leg_modes.legacy_leg_pulses(body)
    # Left leg swung forward → l_hip_yaw pulled off 500; l_hip_pitch untouched
    assert pulses["l_hip_yaw"] != 500
    assert pulses["l_hip_pitch"] == STAND_PULSE["l_hip_pitch"]
    # 30° forward → 500 - 30*4.17 ≈ 375, clamped within [300, 600]
    assert 300 <= pulses["l_hip_yaw"] <= 600
    assert pulses["l_hip_yaw"] == pytest.approx(500 - 30 * (1000 / 240), abs=2)


def test_legacy_missing_world_falls_back_to_stand():
    body = [_empty_landmark() for _ in range(33)]
    for lm in body:
        del lm["xw"]  # no world coords
    pulses = leg_modes.legacy_leg_pulses(body)
    assert pulses == {j: STAND_PULSE[j] for j in leg_modes.LEG_JOINTS}


def test_legacy_pulses_stay_in_tested_ranges():
    """Even extreme thigh angles clamp to the user-tested servo ranges."""
    body = _body_with_legs(l_knee=(+0.5, 0.05, -0.4), r_knee=(-0.5, 0.05, -0.4))
    pulses = leg_modes.legacy_leg_pulses(body)
    assert 300 <= pulses["l_hip_yaw"] <= 600
    assert 400 <= pulses["r_hip_yaw"] <= 700
    assert 400 <= pulses["l_hip_roll"] <= 600
    assert 400 <= pulses["r_hip_roll"] <= 600


# ── Mode 3: classify → canned pose ───────────────────────────────────────────


@pytest.mark.parametrize("class_name", [
    "dab", "hand-raised", "muscles", "superhero", "t-pose", "thinker", "warrior2",
])
def test_classify_returns_all_leg_servos_from_pose(class_name):
    pulses = leg_modes.classify_leg_pulses(class_name)
    assert set(pulses) == set(leg_modes.LEG_JOINTS)
    pose = motions.get_motion(class_name)[0][0]
    for joint in leg_modes.LEG_JOINTS:
        if joint in pose:
            assert pulses[joint] == pose[joint], joint


def test_classify_warrior2_takes_wide_stance():
    """warrior2's canned pose has a real leg stance (knees/hips off stand),
    so the leg pulses differ from a plain stand."""
    pulses = leg_modes.classify_leg_pulses("warrior2")
    stand = {j: STAND_PULSE[j] for j in leg_modes.LEG_JOINTS}
    assert pulses != stand


def test_classify_unknown_class_is_stand():
    pulses = leg_modes.classify_leg_pulses("not-a-pose")
    assert pulses == {j: STAND_PULSE[j] for j in leg_modes.LEG_JOINTS}


def test_classify_leg_targets_convert_cleanly():
    """End-to-end for mode 3 legs: class → pulses → sim radians, all finite."""
    pulses = leg_modes.classify_leg_pulses("warrior2")
    targets = leg_modes.leg_pulses_to_targets(pulses)
    assert set(targets) == set(leg_modes.LEG_JOINTS)
    assert all(math.isfinite(v) for v in targets.values())


# ── Mode 4: buckets ──────────────────────────────────────────────────────────


def _lmk(x: float, vis: float = 1.0) -> dict:
    """Image-space landmark (only x matters for the positional hip-yaw test)."""
    return {"x": x, "y": 0.5, "z": 0.0, "visibility": vis}


def _hip_yaw_body(l_hip_x, r_hip_x, l_knee_x, r_knee_x, l_sho_x, r_sho_x) -> list[dict]:
    b = [_lmk(0.5) for _ in range(33)]
    g = leg_modes.geometry
    b[g.LEFT_HIP], b[g.RIGHT_HIP] = _lmk(l_hip_x), _lmk(r_hip_x)
    b[g.LEFT_KNEE], b[g.RIGHT_KNEE] = _lmk(l_knee_x), _lmk(r_knee_x)
    b[g.LEFT_SHOULDER], b[g.RIGHT_SHOULDER] = _lmk(l_sho_x), _lmk(r_sho_x)
    return b


@pytest.mark.parametrize("avg_deg,expected", [
    (0.0, "high"), (29.9, "high"),
    (30.0, "stand"), (50.0, "stand"), (65.0, "stand"),
    (65.1, "low"), (120.0, "low"),
])
def test_knee_ankle_bucket_thresholds(avg_deg, expected):
    """Thresholds: <30 high, 30-65 stand, >65 low.

    geometry.knee_bend returns ~0deg for a STRAIGHT leg and grows as the knee
    bends, so a small angle means the person is standing tall ("high" stance)
    and a large angle means they're crouched ("low" stance)."""
    assert leg_modes._knee_ankle_bucket_from_avg_deg(avg_deg) == expected


# Person facing a mirrored camera: left side sits at larger image-x, right side
# smaller. Shoulders wider than hips (l_sho 0.66 > l_hip 0.60; r_sho 0.34 < r_hip 0.40).
@pytest.mark.parametrize("knee_x,expected", [
    (0.55, "in"),     # inward of hip (0.60)
    (0.60, "in"),     # exactly at hip -> in (boundary inclusive)
    (0.63, "stand"),  # between hip and shoulder
    (0.66, "stand"),  # exactly at shoulder -> stand
    (0.72, "out"),    # outward of shoulder (0.66)
])
def test_hip_yaw_left_horizontal(knee_x, expected):
    body = _hip_yaw_body(0.60, 0.40, knee_x, 0.40, 0.66, 0.34)
    assert leg_modes._hip_yaw_bucket_side(body, "left") == expected


@pytest.mark.parametrize("knee_x,expected", [
    (0.45, "in"),     # inward of hip (0.40) — larger x is inward on the right side
    (0.40, "in"),
    (0.37, "stand"),
    (0.30, "out"),    # outward of shoulder (0.34)
])
def test_hip_yaw_right_horizontal(knee_x, expected):
    """Right side's 'outward' is the opposite image-x direction from the left,
    handled by the outward-sign derivation from the two hips."""
    body = _hip_yaw_body(0.60, 0.40, 0.60, knee_x, 0.66, 0.34)
    assert leg_modes._hip_yaw_bucket_side(body, "right") == expected


def test_hip_yaw_legs_independent():
    """One leg can land 'in' while the other is 'out' — hip yaw is per-leg."""
    # left knee inward (0.55 < hip 0.60), right knee outward (0.30 < shoulder 0.34)
    body = _hip_yaw_body(0.60, 0.40, 0.55, 0.30, 0.66, 0.34)
    assert leg_modes._hip_yaw_bucket_side(body, "left") == "in"
    assert leg_modes._hip_yaw_bucket_side(body, "right") == "out"


def test_raw_bucket_readouts_reports_knee_deg_and_hip_yaw_bucket():
    body = _hip_yaw_body(0.60, 0.40, 0.63, 0.37, 0.66, 0.34)
    out = leg_modes.raw_bucket_readouts(body)
    assert set(out) == {
        "knee_bend_l_deg", "knee_bend_r_deg", "hip_yaw_l_bucket", "hip_yaw_r_bucket",
    }
    # These landmarks have no world coords -> knee angle unavailable, hip-yaw bucket computed.
    assert out["knee_bend_l_deg"] is None
    assert out["hip_yaw_l_bucket"] == "stand"
    assert out["hip_yaw_r_bucket"] == "stand"
