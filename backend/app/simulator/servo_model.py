"""How stiff the simulated servos are.

"stiff" (default): the model as authored -- every position servo kp=50,
kv=5. On one foot it holds the body rigidly, so the sim showed no sag.

"hardware": every leg servo softened to HARDWARE_LEG_KP. The real robot,
standing on one foot with the other 20% up, sagged ~10 deg toward the
lifted foot and held there (2026-10-02; docs/cbf-whole-body-progress.md
Phase 2.17). Fitted by replaying the exact hardware-check lift in the sim
(scratchpad fit, recorded in Phase 2.19):

  leg kp   left lift   right lift
  50          0.6         2.3     (stiff: no sag)
  15          7.2         7.8     <- chosen: closest to the robot, both sides
  13-18       3-9         -1-9    (balanced near an edge: neighbours jump)

Softening only the roll servos, or adding gear slack, sagged one side only.
This reproduces the SIZE of the sag, not how it responds to every change
(a 1.2x slide went 10.9 -> 8.8 deg on the robot, 7.2 -> 8.4 here), so test
balance fixes across kp 13-18, not just 15.
"""

from __future__ import annotations

import mujoco

LEG_SERVOS = frozenset(
    f"{side}_{j}" for side in "lr"
    for j in ("hip_yaw", "hip_roll", "hip_pitch", "knee", "ank_pitch", "ank_roll")
)
HARDWARE_LEG_KP = 15.0
# Damping scaled with stiffness, as the authored servos (kv/kp = 0.1).
KV_PER_KP = 0.1
SERVO_MODELS = ("stiff", "hardware")


def apply_servo_model(model: mujoco.MjModel, name: str, leg_kp: float = HARDWARE_LEG_KP) -> None:
    """Set the leg servos' stiffness for `name` ("stiff" leaves them as authored).
    `leg_kp` overrides the hardware stiffness, for testing across the range."""
    if name not in SERVO_MODELS:
        raise ValueError(f"unknown servo model {name!r}; expected one of {SERVO_MODELS}")
    if name == "stiff":
        return
    for i in range(model.nu):
        joint = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, model.actuator_trnid[i, 0])
        if joint in LEG_SERVOS:
            # MuJoCo position actuator: force = kp*ctrl - kp*q - kv*qdot
            model.actuator_gainprm[i, 0] = leg_kp
            model.actuator_biasprm[i, 1] = -leg_kp
            model.actuator_biasprm[i, 2] = -leg_kp * KV_PER_KP
