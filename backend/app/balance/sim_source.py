"""MuJoCo sensor source for the balance controller.

Reads the AiNex model's existing IMU-equivalent sensors (defined in
assets/ainex/ainex.xml, following the MuJoCo Playground pattern) into an
AttitudeReading. This is the sim-side "sensor adapter" the plan
(docs/balance-controller.md §3) describes — BalanceController itself
never imports mujoco; this module is the only place that converts raw
sensor data into the controller's plain-float input, so swapping in a
real-IMU adapter later (Phase 3) doesn't touch the controller at all.

Uses the `upvector` sensor (a `framezaxis` sensor: the "imu" site's local
+Z axis, expressed in WORLD coordinates) rather than decomposing the full
`body_quat` orientation quaternion. This is deliberate, not just
convenient: `body_quat` turns out to carry a nontrivial baked-in rotation
offset even at the upright `stand` keyframe (verified empirically —
body_quat != identity there), while `upvector` already accounts for that
and reads exactly [0, 0, 1] when upright. It's also yaw-invariant, which
is physically correct (spinning around vertical doesn't affect balance).
Rate uses `global_angvel` (a `frameangvel` sensor, also world-frame) for
the same reason — NOT the `gyro` sensor, which reports the site's LOCAL
frame angular velocity and would need an extra rotation to compare
against `upvector`'s world-frame numbers.

Sign convention — empirically verified against the real model, not
derived on paper (see backend/tests/test_balance_sim_source.py):
    pitch_rad  = atan2(ux, uz)   — matches rotation about world +Y directly
    roll_rad   = atan2(-uy, uz)  — needs the negation; matches rotation
                                   about world +X (rotating about +X was
                                   found to push the up-vector's Y
                                   component NEGATIVE, so this flips it)
    pitch_rate = global_angvel[1]
    roll_rate  = global_angvel[0]
Both rate signs matched their corresponding position formula (increasing
rate predicts increasing position) with no further flip needed — checked
directly by stepping physics with a known angular velocity, not assumed.

What's still NOT verified: whether world +X/+Y map to anything meaningful
on the physical robot (e.g. "leaning toward its own right" for +roll) —
that requires the real IMU (Phase 3) or a closer read of the leg
attachment geometry, neither done here. What IS verified: this reading is
internally self-consistent (tilt and its rate agree on which way is
"increasing"), which is what the closed-loop test in
backend/tests/test_balance_sim_source.py actually depends on — it proves
the controller reduces a real physical disturbance using this reading,
regardless of which geographic direction the numbers correspond to.
"""

from __future__ import annotations

import math

import mujoco

from app.balance.controller import AttitudeReading

_UPVECTOR_SENSOR = "upvector"
_ANGVEL_SENSOR = "global_angvel"


def _sensor_slice(model: mujoco.MjModel, name: str) -> slice:
    sid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SENSOR, name)
    if sid < 0:
        raise ValueError(f"sensor '{name}' not found in model")
    adr = int(model.sensor_adr[sid])
    dim = int(model.sensor_dim[sid])
    return slice(adr, adr + dim)


def read_attitude(model: mujoco.MjModel, data: mujoco.MjData) -> AttitudeReading:
    """Read current attitude + rate from the model's world-frame sensors.

    Caller must have already called mj_forward or mj_step this tick —
    sensordata is only as current as the last evaluation.
    """
    up = data.sensordata[_sensor_slice(model, _UPVECTOR_SENSOR)]
    angvel = data.sensordata[_sensor_slice(model, _ANGVEL_SENSOR)]

    ux, uy, uz = float(up[0]), float(up[1]), float(up[2])
    pitch_rad = math.atan2(ux, uz)
    roll_rad = math.atan2(-uy, uz)

    roll_rate = float(angvel[0])
    pitch_rate = float(angvel[1])

    return AttitudeReading(
        pitch_rad=pitch_rad, roll_rad=roll_rad,
        pitch_rate=pitch_rate, roll_rate=roll_rate,
    )
