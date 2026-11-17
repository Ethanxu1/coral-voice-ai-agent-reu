"""Hand-tunable robot hardware parameters.

This is the single file to edit when adjusting per-joint safe servo ranges
during hardware bring-up/testing on the physical AiNex. Nothing else in the
codebase should define a per-joint range literal -- add it here.

These ranges are a SOFTWARE safety clamp on top of each servo's raw 0-1000
pulse range (240 degrees of travel). They exist to protect the physical
robot -- avoiding mechanical end-stops and one known damaged servo -- not to
define "comfortable" poses. The self-collision and fall-stability checkers
(backend/app/collision/) are a SEPARATE, independent safety layer that still
applies no matter what these ranges allow.

## Wire-twist rotation joints

l_el_pitch / r_el_pitch (forearm rotation -- the "elbow Rot In/Out" test
commands; the joint name says "pitch" but this is physically an axial twist
of the forearm, see servo_config.py's SERVO_ID_MAP comments) and l_hip_yaw /
r_hip_yaw (hip internal/external rotation -- "hip Rot In/Out") are the only
joints that physically twist about a limb's own long axis, which is what
can wind up internal wiring if over-rotated. Every other joint below is a
hinge (bend) and doesn't have this failure mode.

## 2026-09-12 relaxation

At the user's request, every range below was widened (never tightened) from
values that had mostly been tuned to specific dance-move poses (e.g. the
leg-bucket routine) rather than to an actual measured wire/mechanical safety
limit. This is a PLACEHOLDER pending physical hardware verification --
TIGHTEN INDIVIDUAL JOINTS ONCE YOU'VE TESTED how far each one can move
before the wiring visibly strains or it hits an uncomfortable mechanical
limit. Do not run an unattended demo on unverified ranges, especially for
hip_pitch/knee (marked below as never hardware-swept even before this
widening).

r_el_yaw is the one exception: it is a physically DAMAGED servo (see
hardware_controller/hardware_angle_utils history), not just a conservative
default, so its range was left exactly as previously validated rather than
being widened by the general policy above -- do not relax it further
without first confirming on hardware that the damaged servo tolerates it.
"""

# SINGLE SOURCE OF TRUTH for joint range: backend/app/validation.py derives
# its sim-radian JOINT_LIMITS from this table via hardware_units_to_rad, so
# sim clamping and hardware clamping stay in lockstep. Every range MUST
# contain its joint's STAND_PULSE (backend/app/robot/servo_config.py) -- a
# range that excludes stand makes the stand pose itself unreachable through
# any clamped path.
JOINT_SAFE_RANGES: dict[str, tuple[int, int]] = {
    # --- Wire-twist rotation joints: relaxed placeholder, verify on hardware ---
    "l_el_pitch":  (100, 900),   # servo 17 — forearm rotation
    "r_el_pitch":  (100, 900),   # servo 18 — forearm rotation
    "l_hip_yaw":   (100, 900),   # servo 11 — hip rotation
    "r_hip_yaw":   (100, 900),   # servo 12 — hip rotation

    # --- Everything else: end-stop / mechanical safety margins ---
    "l_ank_roll":  (100, 900),   # servo 1
    "r_ank_roll":  (100, 900),   # servo 2
    "l_ank_pitch": (0, 1000),    # servo 3 — stand=640
    "r_ank_pitch": (0, 760),     # servo 4 — stand=360
    "l_sho_pitch": (150, 1000),  # servo 13 — stand=835
    "r_sho_pitch": (0, 830),     # servo 14 — stand=165
    "l_sho_roll":  (430, 1000),  # servo 15 — stand=830
    "r_sho_roll":  (0, 613),     # servo 16 — stand=170
    "l_el_yaw":    (0, 550),     # servo 19 — elbow bend
    "r_el_yaw":    (450, 850),   # servo 20 — elbow bend, DAMAGED SERVO: not
                                  # relaxed by the 2026-09-12 policy above,
                                  # never command below 450 (hard floor)
    "l_knee":      (100, 900),   # servo 5  — stand=500, NOT hardware-swept
    "r_knee":      (100, 900),   # servo 6  — stand=500, NOT hardware-swept
    "l_hip_pitch": (0, 750),     # servo 7  — stand=350, NOT hardware-swept
    "r_hip_pitch": (250, 1000),  # servo 8  — stand=650, NOT hardware-swept
    "l_hip_roll":  (100, 900),   # servo 9  — was user-tested: 400=outward 30°, 600=inward 20°
    "r_hip_roll":  (100, 900),   # servo 10 — was user-tested: 400=inward 20°, 600=outward 30°
}
