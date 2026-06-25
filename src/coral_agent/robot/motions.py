"""Servo pulse poses and named motion sequences.

Pulse dicts map joint name → pulse value (0–1000 scale, 500 = centre).
A motion is a list of ``(pulse_dict, duration_ms)`` frames — the format the
``/body_commands`` ROS service and ``/motion`` HTTP endpoint consume.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# ── Servo pulse poses ─────────────────────────────────────────────────────────

STAND_PULSE = {
    'l_ank_roll':  500,  'r_ank_roll':  500,
    'l_ank_pitch': 640,  'r_ank_pitch': 360,
    'l_knee':      500,  'r_knee':      500,
    'l_hip_pitch': 350,  'r_hip_pitch': 650,
    'l_hip_roll':  500,  'r_hip_roll':  500,
    'l_hip_yaw':   500,  'r_hip_yaw':   500,
    'l_sho_pitch': 835,  'r_sho_pitch': 165,
    'l_sho_roll':  830,  'r_sho_roll':  170,
    'l_el_pitch':  500,  'r_el_pitch':  500,
    'l_el_yaw':    150,  'r_el_yaw':    850,
    'l_gripper':   500,  'r_gripper':   500,
    'head_pan':    500,  'head_tilt':   500,
}

STAND_LOW_PULSE = {
    'l_ank_roll':  500,  'r_ank_roll':  500,
    'l_ank_pitch': 720,  'r_ank_pitch': 280,
    'l_knee':      650,  'r_knee':      350,
    'l_hip_pitch': 245,  'r_hip_pitch': 755,
    'l_hip_roll':  500,  'r_hip_roll':  500,
    'l_hip_yaw':   500,  'r_hip_yaw':   500,
    'l_sho_pitch': 835,  'r_sho_pitch': 165,
    'l_sho_roll':  830,  'r_sho_roll':  170,
    'l_el_pitch':  500,  'r_el_pitch':  500,
    'l_el_yaw':     70,  'r_el_yaw':    930,
    'l_gripper':   500,  'r_gripper':   500,
    'head_pan':    500,  'head_tilt':   500,
}

DAB_PULSE = {
    'l_ank_roll':  500,  'r_ank_roll':  500,
    'l_ank_pitch': 720,  'r_ank_pitch': 280,
    'l_knee':      650,  'r_knee':      350,
    'l_hip_pitch': 240,  'r_hip_pitch': 755,
    'l_hip_roll':  500,  'r_hip_roll':  500,
    'l_hip_yaw':   500,  'r_hip_yaw':   500,
    'l_sho_pitch': 835,  'r_sho_pitch': 675,
    'l_sho_roll':  585,  'r_sho_roll':  225,
    'l_el_pitch':  500,  'r_el_pitch':  120,
    'l_el_yaw':    465,  'r_el_yaw':    890,
    'l_gripper':   500,  'r_gripper':   500,
    'head_pan':    500,  'head_tilt':   500,
}

THINKER_PULSE = {
    'l_ank_roll':  499,  'r_ank_roll':  494,
    'l_ank_pitch': 641,  'r_ank_pitch': 356,
    'l_knee':      476,  'r_knee':      502,
    'l_hip_pitch': 351,  'r_hip_pitch': 651,
    'l_hip_roll':  501,  'r_hip_roll':  497,
    'l_hip_yaw':   500,  'r_hip_yaw':   557,
    'l_sho_pitch': 518,  'r_sho_pitch': 436,
    'l_sho_roll':  784,  'r_sho_roll':  171,
    'l_el_pitch':  655,  'r_el_pitch':  162,
    'l_el_yaw':     53,  'r_el_yaw':    849,
    'l_gripper':   625,  'r_gripper':   499,
}

SUPERHERO_PULSE = {
    'l_ank_roll':  499,  'r_ank_roll':  501,
    'l_ank_pitch': 639,  'r_ank_pitch': 358,
    'l_knee':      505,  'r_knee':      493,
    'l_hip_pitch': 348,  'r_hip_pitch': 648,
    'l_hip_roll':  498,  'r_hip_roll':  498,
    'l_hip_yaw':   499,  'r_hip_yaw':   498,
    'l_sho_pitch': 824,  'r_sho_pitch': 174,
    'l_sho_roll':  704,  'r_sho_roll':  316,
    'l_el_pitch':  652,  'r_el_pitch':  348,
    'l_el_yaw':     90,  'r_el_yaw':    907,
    'l_gripper':   504,  'r_gripper':   499,
}

WARRIOR_PULSE = {
    'l_ank_roll':  505,  'r_ank_roll':  498,
    'l_ank_pitch': 780,  'r_ank_pitch': 572,
    'l_knee':      428,  'r_knee':      559,
    'l_hip_pitch': 604,  'r_hip_pitch': 750,
    'l_hip_roll':  509,  'r_hip_roll':  501,
    'l_hip_yaw':   561,  'r_hip_yaw':   557,
    'l_sho_pitch': 981,  'r_sho_pitch': 662,
    'l_sho_roll':  815,  'r_sho_roll':  211,
    'l_el_pitch':  506,  'r_el_pitch':  534,
    'l_el_yaw':    481,  'r_el_yaw':    531,
    'l_gripper':   499,  'r_gripper':   499,
}

HANDS_UP_PULSE = {
    'l_ank_roll':  499,  'r_ank_roll':  502,
    'l_ank_pitch': 638,  'r_ank_pitch': 354,
    'l_knee':      502,  'r_knee':      490,
    'l_hip_pitch': 346,  'r_hip_pitch': 649,
    'l_hip_roll':  500,  'r_hip_roll':  498,
    'l_hip_yaw':   502,  'r_hip_yaw':   498,
    'l_sho_pitch': 185,  'r_sho_pitch': 841,
    'l_sho_roll':  729,  'r_sho_roll':  254,
    'l_el_pitch':  625,  'r_el_pitch':  413,
    'l_el_yaw':    170,  'r_el_yaw':    770,
    'l_gripper':   499,  'r_gripper':   499,
}

LEFT_HAND_UP_PULSE = {
    'l_ank_roll':  501,  'r_ank_roll':  501,
    'l_ank_pitch': 638,  'r_ank_pitch': 358,
    'l_knee':      503,  'r_knee':      494,
    'l_hip_pitch': 348,  'r_hip_pitch': 648,
    'l_hip_roll':  500,  'r_hip_roll':  498,
    'l_hip_yaw':   500,  'r_hip_yaw':   500,
    'l_sho_pitch': 189,  'r_sho_pitch': 165,
    'l_sho_roll':  730,  'r_sho_roll':  171,
    'l_el_pitch':  625,  'r_el_pitch':  498,
    'l_el_yaw':    171,  'r_el_yaw':    850,
    'l_gripper':   499,  'r_gripper':   499,
}

RIGHT_HAND_UP_PULSE = {
    'l_ank_roll':  499,  'r_ank_roll':  501,
    'l_ank_pitch': 642,  'r_ank_pitch': 360,
    'l_knee':      504,  'r_knee':      493,
    'l_hip_pitch': 348,  'r_hip_pitch': 651,
    'l_hip_roll':  499,  'r_hip_roll':  498,
    'l_hip_yaw':   502,  'r_hip_yaw':   502,
    'l_sho_pitch': 833,  'r_sho_pitch': 837,
    'l_sho_roll':  831,  'r_sho_roll':  254,
    'l_el_pitch':  500,  'r_el_pitch':  413,
    'l_el_yaw':    152,  'r_el_yaw':    732,
    'l_gripper':   499,  'r_gripper':   499,
}

T_POSE_PULSE = {
    'l_ank_roll':  499,  'r_ank_roll':  501,
    'l_ank_pitch': 638,  'r_ank_pitch': 358,
    'l_knee':      504,  'r_knee':      495,
    'l_hip_pitch': 348,  'r_hip_pitch': 648,
    'l_hip_roll':  498,  'r_hip_roll':  498,
    'l_hip_yaw':   499,  'r_hip_yaw':   499,
    'l_sho_pitch': 718,  'r_sho_pitch': 294,
    'l_sho_roll':  513,  'r_sho_roll':  520,
    'l_el_pitch':  498,  'r_el_pitch':  500,
    'l_el_yaw':    504,  'r_el_yaw':    454,
    'l_gripper':   499,  'r_gripper':   499,
}

MUSCLES_PULSE = {
    'l_ank_roll':  499,  'r_ank_roll':  501,
    'l_ank_pitch': 642,  'r_ank_pitch': 358,
    'l_knee':      503,  'r_knee':      494,
    'l_hip_pitch': 348,  'r_hip_pitch': 651,
    'l_hip_roll':  499,  'r_hip_roll':  498,
    'l_hip_yaw':   502,  'r_hip_yaw':   501,
    'l_sho_pitch': 348,  'r_sho_pitch': 654,
    'l_sho_roll':  601,  'r_sho_roll':  450,
    'l_el_pitch':  507,  'r_el_pitch':  498,
    'l_el_yaw':     26,  'r_el_yaw':    905,
    'l_gripper':   610,  'r_gripper':   374,
}

# ── Motion sequences ──────────────────────────────────────────────────────────

Motion = List[Tuple[Dict[str, int], int]]

POSE_DURATION_MS = 800


def _single(pulse: Dict[str, int], duration_ms: int = POSE_DURATION_MS) -> Motion:
    return [(pulse, duration_ms)]


WAVE: Motion = [
    ({
        'l_ank_roll': 500,  'r_ank_roll': 500,
        'l_ank_pitch': 640, 'r_ank_pitch': 360,
        'l_knee': 500,      'r_knee': 500,
        'l_hip_pitch': 330, 'r_hip_pitch': 670,
        'l_hip_roll': 500,  'r_hip_roll': 500,
        'l_hip_yaw': 500,   'r_hip_yaw': 500,
        'l_sho_pitch': 1000, 'r_sho_pitch': 0,
        'l_sho_roll': 500,  'r_sho_roll': 500,
        'l_el_pitch': 500,  'r_el_pitch': 500,
        'l_el_yaw': 268,    'r_el_yaw': 1000,
        'l_gripper': 500,   'r_gripper': 500,
    }, 400),
    ({
        'l_ank_roll': 500,  'r_ank_roll': 500,
        'l_ank_pitch': 640, 'r_ank_pitch': 360,
        'l_knee': 500,      'r_knee': 500,
        'l_hip_pitch': 330, 'r_hip_pitch': 670,
        'l_hip_roll': 500,  'r_hip_roll': 500,
        'l_hip_yaw': 500,   'r_hip_yaw': 500,
        'l_sho_pitch': 1000, 'r_sho_pitch': 0,
        'l_sho_roll': 500,  'r_sho_roll': 500,
        'l_el_pitch': 500,  'r_el_pitch': 500,
        'l_el_yaw': 0,      'r_el_yaw': 750,
        'l_gripper': 500,   'r_gripper': 500,
    }, 400),
    ({
        'l_ank_roll': 500,  'r_ank_roll': 500,
        'l_ank_pitch': 640, 'r_ank_pitch': 360,
        'l_knee': 500,      'r_knee': 500,
        'l_hip_pitch': 330, 'r_hip_pitch': 670,
        'l_hip_roll': 500,  'r_hip_roll': 500,
        'l_hip_yaw': 500,   'r_hip_yaw': 500,
        'l_sho_pitch': 1000, 'r_sho_pitch': 0,
        'l_sho_roll': 500,  'r_sho_roll': 500,
        'l_el_pitch': 500,  'r_el_pitch': 500,
        'l_el_yaw': 268,    'r_el_yaw': 1000,
        'l_gripper': 500,   'r_gripper': 500,
    }, 400),
    ({
        'l_ank_roll': 500,  'r_ank_roll': 500,
        'l_ank_pitch': 640, 'r_ank_pitch': 360,
        'l_knee': 500,      'r_knee': 500,
        'l_hip_pitch': 330, 'r_hip_pitch': 670,
        'l_hip_roll': 500,  'r_hip_roll': 500,
        'l_hip_yaw': 500,   'r_hip_yaw': 500,
        'l_sho_pitch': 1000, 'r_sho_pitch': 0,
        'l_sho_roll': 500,  'r_sho_roll': 500,
        'l_el_pitch': 500,  'r_el_pitch': 500,
        'l_el_yaw': 0,      'r_el_yaw': 750,
        'l_gripper': 500,   'r_gripper': 500,
    }, 400),
    ({
        'l_ank_roll': 500,  'r_ank_roll': 500,
        'l_ank_pitch': 640, 'r_ank_pitch': 360,
        'l_knee': 500,      'r_knee': 500,
        'l_hip_pitch': 330, 'r_hip_pitch': 670,
        'l_hip_roll': 500,  'r_hip_roll': 500,
        'l_hip_yaw': 500,   'r_hip_yaw': 500,
        'l_sho_pitch': 300, 'r_sho_pitch': 0,
        'l_sho_roll': 500,  'r_sho_roll': 500,
        'l_el_pitch': 500,  'r_el_pitch': 500,
        'l_el_yaw': 125,    'r_el_yaw': 875,
        'l_gripper': 500,   'r_gripper': 500,
    }, 400),
    ({
        'l_ank_roll': 500,  'r_ank_roll': 500,
        'l_ank_pitch': 640, 'r_ank_pitch': 360,
        'l_knee': 500,      'r_knee': 500,
        'l_hip_pitch': 330, 'r_hip_pitch': 670,
        'l_hip_roll': 500,  'r_hip_roll': 500,
        'l_hip_yaw': 500,   'r_hip_yaw': 500,
        'l_sho_pitch': 1000, 'r_sho_pitch': 700,
        'l_sho_roll': 500,  'r_sho_roll': 500,
        'l_el_pitch': 500,  'r_el_pitch': 500,
        'l_el_yaw': 125,    'r_el_yaw': 875,
        'l_gripper': 500,   'r_gripper': 500,
    }, 400),
    ({
        'l_ank_roll': 500,  'r_ank_roll': 500,
        'l_ank_pitch': 640, 'r_ank_pitch': 360,
        'l_knee': 500,      'r_knee': 500,
        'l_hip_pitch': 330, 'r_hip_pitch': 670,
        'l_hip_roll': 500,  'r_hip_roll': 500,
        'l_hip_yaw': 500,   'r_hip_yaw': 500,
        'l_sho_pitch': 300, 'r_sho_pitch': 0,
        'l_sho_roll': 500,  'r_sho_roll': 500,
        'l_el_pitch': 500,  'r_el_pitch': 500,
        'l_el_yaw': 125,    'r_el_yaw': 875,
        'l_gripper': 500,   'r_gripper': 500,
    }, 400),
    ({
        'l_ank_roll': 500,  'r_ank_roll': 500,
        'l_ank_pitch': 640, 'r_ank_pitch': 360,
        'l_knee': 500,      'r_knee': 500,
        'l_hip_pitch': 330, 'r_hip_pitch': 670,
        'l_hip_roll': 500,  'r_hip_roll': 500,
        'l_hip_yaw': 500,   'r_hip_yaw': 500,
        'l_sho_pitch': 1000, 'r_sho_pitch': 700,
        'l_sho_roll': 500,  'r_sho_roll': 500,
        'l_el_pitch': 500,  'r_el_pitch': 500,
        'l_el_yaw': 125,    'r_el_yaw': 875,
        'l_gripper': 500,   'r_gripper': 500,
    }, 400),
    ({
        'l_ank_roll': 500,  'r_ank_roll': 500,
        'l_ank_pitch': 640, 'r_ank_pitch': 360,
        'l_knee': 500,      'r_knee': 500,
        'l_hip_pitch': 330, 'r_hip_pitch': 670,
        'l_hip_roll': 500,  'r_hip_roll': 500,
        'l_hip_yaw': 500,   'r_hip_yaw': 500,
        'l_sho_pitch': 835, 'r_sho_pitch': 165,
        'l_sho_roll': 830,  'r_sho_roll': 170,
        'l_el_pitch': 500,  'r_el_pitch': 500,
        'l_el_yaw': 70,     'r_el_yaw': 930,
        'l_gripper': 500,   'r_gripper': 500,
    }, 500),
]

MOTIONS: Dict[str, Motion] = {
    "wave":       WAVE,
    "stand":      _single(STAND_PULSE, 1500),
    "t-pose":     _single(T_POSE_PULSE),
    "dab":        _single(DAB_PULSE),
    "superhero":  _single(SUPERHERO_PULSE),
    "thinker":    _single(THINKER_PULSE),
    "muscles":    _single(MUSCLES_PULSE),
    "hand-raised": _single(HANDS_UP_PULSE),
    "warrior2":   _single(WARRIOR_PULSE),
}


def get_motion(name: str) -> Motion | None:
    """Return the named motion sequence, or ``None`` if unknown."""
    return MOTIONS.get(name)
