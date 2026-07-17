"""Interactive authoring tool for the sim's `stand` keyframe.

The problem it solves: the MuJoCo `stand` keyframe (assets/ainex/ainex.xml) is
hand-authored, and its per-joint radians don't match how the *physical* robot
actually stands at STAND_PULSE. This tool lets you jog the sim to match the real
robot (eyeball it, or dial exact protractor degrees), then exports every place
the stand pose is duplicated so they stay consistent:

    assets/ainex/ainex.xml                     the `stand` keyframe qpos
    coral_agent/robot/hardware_angle_utils.py  HW_STAND_RAD  (the pulse<->rad anchor)
    coral_agent/primitives.py                  STAND_*_SHO_ROLL / STAND_*_EL_YAW
    coral_agent/vision/pose_to_robot.py        _STAND_*_SHO_ROLL

Why all four must move together: hardware_units_to_rad(STAND_PULSE[j], j) returns
HW_STAND_RAD[j] by definition, and the sim renders the keyframe. If the keyframe
changes but HW_STAND_RAD doesn't, /set-pose and /motion desync from the sim again.

Workflow:
    1. Put the real robot in its stand pose (STAND_PULSE). Keep it in view.
    2. Run this tool; the sim opens at the current keyframe.
    3. Jog each joint until the sim matches the real robot. `deg` takes protractor
       degrees directly; watch the viewer to confirm the sign.
    4. `export` — paste the printed blocks into the four files.

Usage (macOS needs mjpython for the viewer):
    mjpython tools/author_stand.py
    python   tools/author_stand.py            # Linux / where python can open the viewer
    ROBOT_IP=192.168.8.219 mjpython tools/author_stand.py   # enables `robot-stand`

Commands (type `help` in the prompt for the live list).
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import mujoco

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from coral_agent.robot.servo_config import STAND_PULSE  # noqa: E402
from coral_agent.simulator import AiNexSimulator  # noqa: E402

# Keyframe qpos joint order (matches the body-tree order MuJoCo writes qpos in;
# the tool reads the true addresses from the model, this list is only for the
# human-readable per-joint printout).
JOINT_ORDER = [
    "r_hip_yaw", "r_hip_roll", "r_hip_pitch", "r_knee", "r_ank_pitch", "r_ank_roll",
    "l_hip_yaw", "l_hip_roll", "l_hip_pitch", "l_knee", "l_ank_pitch", "l_ank_roll",
    "head_pan", "head_tilt",
    "r_sho_pitch", "r_sho_roll", "r_el_pitch", "r_el_yaw", "r_gripper",
    "l_sho_pitch", "l_sho_roll", "l_el_pitch", "l_el_yaw", "l_gripper",
]

# Joints that other files hardcode as stand constants (see module docstring).
_PRIMITIVES_CONSTS = {
    "l_sho_roll": "STAND_L_SHO_ROLL",
    "r_sho_roll": "STAND_R_SHO_ROLL",
    "l_el_yaw": "STAND_L_EL_YAW",
    "r_el_yaw": "STAND_R_EL_YAW",
}


def _set_rad(sim: AiNexSimulator, joint: str, rad: float) -> None:
    """Set a joint's ctrl target directly (no JOINT_LIMITS clamp — we're defining
    the reference pose, so authoring must be unconstrained)."""
    full = sim.JOINT_NAMES[joint]
    aid = sim._actuator_ids[full]
    with sim._lock:
        sim.data.ctrl[aid] = rad


def _get_rad(sim: AiNexSimulator, joint: str) -> float:
    full = sim.JOINT_NAMES[joint]
    aid = sim._actuator_ids[full]
    with sim._lock:
        return float(sim.data.ctrl[aid])


def _print_show(sim: AiNexSimulator) -> None:
    print("\n  joint            rad      deg")
    print("  " + "-" * 34)
    for j in JOINT_ORDER:
        r = _get_rad(sim, j)
        print(f"  {j:14} {r:+7.3f}  {math.degrees(r):+7.1f}")
    print()


def _export(sim: AiNexSimulator) -> None:
    targets = {j: _get_rad(sim, j) for j in sim.JOINT_NAMES}

    # ── 1. keyframe qpos ─────────────────────────────────────────────
    key_id = mujoco.mj_name2id(sim.model, mujoco.mjtObj.mjOBJ_KEY, "stand")
    qpos = list(sim.model.key_qpos[key_id])  # keep the 7-dof free-root prefix as-is
    for joint, rad in targets.items():
        jid = sim._joint_ids[joint]
        qpos[sim.model.jnt_qposadr[jid]] = rad
    qpos_str = " ".join(f"{v:.4f}" for v in qpos)

    print("\n" + "=" * 70)
    print("1) assets/ainex/ainex.xml — replace the `stand` keyframe qpos:")
    print("=" * 70)
    print(f'    <key name="stand"\n         qpos="{qpos_str}"/>')

    # ── 2. HW_STAND_RAD (non-zero joints only; others default to 0.0) ──
    print("\n" + "=" * 70)
    print("2) coral_agent/robot/hardware_angle_utils.py — set HW_STAND_RAD to:")
    print("   (must match the keyframe exactly; zero joints may be omitted)")
    print("=" * 70)
    print("HW_STAND_RAD: dict[str, float] = {")
    for j in JOINT_ORDER:
        if abs(targets[j]) > 1e-4:
            print(f'    "{j}": {targets[j]:.4f},')
    print("}")

    # ── 3. primitives.py / pose_to_robot.py stand constants ──────────
    print("\n" + "=" * 70)
    print("3) coral_agent/primitives.py — update these constants:")
    print("   (and mirror _STAND_L/R_SHO_ROLL in coral_agent/vision/pose_to_robot.py)")
    print("=" * 70)
    for joint, const in _PRIMITIVES_CONSTS.items():
        print(f"{const} = {targets[joint]:.4f}")

    print("\n" + "=" * 70)
    print("Reminder: the Pi copy (robot/pi/nodes/pose_to_robot.py) has its own")
    print("HW_STAND_RAD/_STAND_* — update it too if/when you re-sync the Pi.")
    print("=" * 70 + "\n")


def _robot_stand() -> None:
    """Best-effort: drive the physical robot to STAND_PULSE so it can serve as the
    visual reference. Only available when ROBOT_IP is set."""
    ip = os.getenv("ROBOT_IP")
    if not ip:
        print("  ROBOT_IP not set — skipping (jog the sim to a real robot you pose separately).")
        return
    try:
        import httpx

        from coral_agent.robot.servo_config import SERVO_ID_MAP

        port = os.getenv("ROBOT_AGENT_PORT", "9000")
        payload = [
            {"servo_id": sid, "position": STAND_PULSE[name], "duration_ms": 1000}
            for name, sid in SERVO_ID_MAP.items()
            if name in STAND_PULSE
        ]
        httpx.post(f"http://{ip}:{port}/move", json=payload, timeout=5.0)
        print(f"  Sent STAND_PULSE to robot at {ip}:{port}.")
    except Exception as e:  # noqa: BLE001
        print(f"  robot-stand failed: {e}")


HELP = """
Commands:
  <joint> <rad>        set a joint to an absolute value in radians   (l_sho_roll -1.25)
  deg <joint> <deg>    set a joint in degrees (protractor-friendly)  (deg l_sho_roll -71.6)
  nudge <joint> <rad>  add a relative offset                         (nudge l_sho_roll +0.05)
  show                 list every joint's current rad + deg
  reset                reload the current stand keyframe
  robot-stand          drive the physical robot to STAND_PULSE (needs ROBOT_IP)
  export               print copy-paste blocks for all four files
  help                 this list
  quit                 exit (does NOT auto-save — use export first)

Joints: r_/l_ + hip_yaw hip_roll hip_pitch knee ank_pitch ank_roll
        sho_pitch sho_roll el_pitch el_yaw gripper, plus head_pan head_tilt
"""


def _handle(sim: AiNexSimulator, line: str) -> bool:
    """Process one command line. Returns False to quit."""
    parts = line.split()
    if not parts:
        return True
    cmd = parts[0].lower()

    if cmd in ("quit", "exit", "q"):
        return False
    if cmd in ("help", "h", "?"):
        print(HELP)
        return True
    if cmd == "show":
        _print_show(sim)
        return True
    if cmd == "reset":
        sim.reset_pose()
        print("  reset to current stand keyframe")
        return True
    if cmd == "robot-stand":
        _robot_stand()
        return True
    if cmd == "export":
        _export(sim)
        return True

    try:
        if cmd == "deg":
            joint, val = parts[1], math.radians(float(parts[2]))
            _set_rad(sim, joint, val)
        elif cmd == "nudge":
            joint = parts[1]
            _set_rad(sim, joint, _get_rad(sim, joint) + float(parts[2]))
        else:
            joint, val = parts[0], float(parts[1])
            _set_rad(sim, joint, val)
    except (IndexError, ValueError):
        print("  ? couldn't parse — type `help`")
        return True
    except KeyError:
        print(f"  ? unknown joint '{parts[1] if cmd in ('deg', 'nudge') else parts[0]}'")
        return True

    joint = parts[1] if cmd in ("deg", "nudge") else parts[0]
    r = _get_rad(sim, joint)
    print(f"  {joint} = {r:+.3f} rad ({math.degrees(r):+.1f}°)")
    return True


def main() -> None:
    sim = AiNexSimulator()
    sim.start_viewer()
    print("\nStand keyframe authoring — sim viewer is open.")
    print("Pose the real robot at STAND_PULSE, then jog the sim to match it.")
    print("Type `help` for commands, `export` when it matches.\n")
    _print_show(sim)

    try:
        while sim.is_running():
            try:
                line = input("stand> ")
            except EOFError:
                break
            if not _handle(sim, line):
                break
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        sim.stop_viewer()
        print("viewer closed — remember to `export` any unsaved changes next time.")


if __name__ == "__main__":
    main()
