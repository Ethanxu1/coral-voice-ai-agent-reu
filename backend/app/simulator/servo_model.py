"""How stiff the simulated servos are.

"stiff" (default): the model as authored -- every position servo kp=50,
kv=5. On one foot it holds the body rigidly, so the sim showed no sag.

"hardware": the ankle-roll servos softened to HARDWARE_ANKLE_ROLL_KP. The real
robot, standing on one foot with the other 20% up, sagged ~10 deg toward the
lifted foot and held there, after a hip slide that itself leaned <1 deg
(2026-10-02; docs/cbf-whole-body-progress.md Phase 2.17). Fitted by replaying
the exact hardware-check lift in the sim (Phase 2.19):

  model                      slide   left lift   right lift
  stiff (kp 50)                ~0      0.6         2.3       no sag
  all leg servos kp 15          --     7.2         7.8       REJECTED: the hip
                                                            rolls barely moved
                                                            (-0.03 of -0.19), so
                                                            the slide never
                                                            happened -- sag for
                                                            the wrong reason
  roll-only soft / gear slack   ~0     1-4         12-20     one-sided
  ankle roll kp <= 10         +4.6    15.5        15.9       <- chosen
  ankle roll kp >= 25          ~-2     ~0          ~0
  real robot                   ~0     10.9 (clean) ~10 (toes touching)

With soft ankles the hips still slide (stiff hips do it), and on one foot the
standing ankle gives until the foot rolls onto its edge: a steady, symmetric
sag, like the robot. It is a sharp threshold (kp 15-25 goes either way).
~15 deg is MORE than the robot's 10: a harder test than reality.
"""

from __future__ import annotations

import mujoco

LEG_SERVOS = frozenset(
    f"{side}_{j}" for side in "lr"
    for j in ("hip_yaw", "hip_roll", "hip_pitch", "knee", "ank_pitch", "ank_roll")
)
SOFT_SERVOS = frozenset({"l_ank_roll", "r_ank_roll"})
HARDWARE_ANKLE_ROLL_KP = 5.0
# Damping scaled with stiffness, as the authored servos (kv/kp = 0.1).
KV_PER_KP = 0.1
SERVO_MODELS = ("stiff", "hardware")


def apply_servo_model(model: mujoco.MjModel, name: str,
                      soft_kp: float = HARDWARE_ANKLE_ROLL_KP) -> None:
    """Set servo stiffness for `name` ("stiff" leaves the model as authored).
    `soft_kp` overrides the soft servos' stiffness, for testing a range."""
    if name not in SERVO_MODELS:
        raise ValueError(f"unknown servo model {name!r}; expected one of {SERVO_MODELS}")
    if name == "stiff":
        return
    for i in range(model.nu):
        joint = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, model.actuator_trnid[i, 0])
        if joint in SOFT_SERVOS:
            # MuJoCo position actuator: force = kp*ctrl - kp*q - kv*qdot
            model.actuator_gainprm[i, 0] = soft_kp
            model.actuator_biasprm[i, 1] = -soft_kp
            model.actuator_biasprm[i, 2] = -soft_kp * KV_PER_KP
