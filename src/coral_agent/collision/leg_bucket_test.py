"""Stability test harness for the "buckets" leg mode (leg_modes.py).

For every (knee_ankle_bucket x hip_yaw_l_bucket x hip_yaw_r_bucket) combination
— 3 x 3 x 3 = 27 total, since hip yaw is leg-independent — drives that stance on
a MuJoCo instance under real physics (gravity + floor contact, not just forward
kinematics) and reports two stability signals:

  1. Head height: the head body's world Z after the robot settles, compared to
     its settled stand height. A large drop means the robot crouched, tipped,
     or fell — a fall-risk signal.
  2. Center of gravity: the whole-model center of mass, as an (x, y) deviation
     from the world origin the robot's base starts at (see ainex.xml's
     `base_link`/`root` freejoint, positioned at x=0, y=0). A large deviation
     means the COM has drifted away from the robot's footprint — a tipping risk.

This has to be a real dynamics rollout, not the kinematic mj_forward approach
CollisionChecker uses: with mj_forward alone the free-floating base is pinned
wherever the stand keyframe put it, so changing leg joint angles moves the feet
away from the floor instead of moving the torso/head — head height would never
change regardless of how extreme the bucket stance is. Here every joint (legs
from the bucket combo, everything else held at stand) is driven through its
position actuator (data.ctrl) and the sim is stepped forward under gravity with
floor contact enabled, so a genuinely unstable stance can actually topple.

Also runs each bucket combo's stand->pose transition through CollisionChecker
(kinematic, cheap) as a correlated signal — the more extreme bucket stances are
exactly the kind of pose likely to self-collide too.

By default opens a native MuJoCo viewer window and steps through all 27 combos
live (settling in real time, holding briefly, then moving on) so you can watch
each stance instead of only reading the JSON — same UX as collision_test.py.

Usage:
    uv run leg-bucket-test                     # run, show the viewer, print a report
    uv run leg-bucket-test out.json            # also save the JSON report there
    CORAL_NO_VIEWER=1 uv run leg-bucket-test   # headless (e.g. CI)
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import mujoco
import mujoco.viewer
from loguru import logger

from coral_agent.collision.collision_checker import CollisionChecker
from coral_agent.vision.leg_modes import HIP_YAW_BUCKETS, KNEE_ANKLE_BUCKETS, combine_bucket_targets

# Fall-risk heuristic: flag a bucket combo if its settled head height drops more
# than this fraction below the settled stand height. Configurable default.
_HEAD_DROP_FALL_THRESHOLD_FRAC = 0.10

_HEAD_BODY_NAME = "head_tilt_link"

# How long to let the robot settle under gravity+contact before measuring.
_SETTLE_SECONDS = 1.5

# How long to hold the settled pose on screen before moving to the next combo.
_HOLD_SECONDS = 1.0

# Sync the viewer every N physics steps during settling (lower = smoother but
# more render overhead). At dt=0.002s, syncing every 4 steps is ~125Hz.
_VIEWER_SYNC_EVERY_N_STEPS = 4


def _reexec_under_mjpython_if_needed() -> None:
    """Re-exec under `mjpython` on macOS so the MuJoCo viewer window can open.

    Mirrors collision_test.py's helper of the same name. No-op off macOS, once
    already re-exec'd, or when CORAL_NO_VIEWER=1.
    """
    if sys.platform != "darwin":
        return
    if os.environ.get("CORAL_MJPYTHON") == "1" or os.environ.get("CORAL_NO_VIEWER") == "1":
        return
    mjpython = Path(sys.executable).with_name("mjpython")
    if not mjpython.exists():
        logger.warning(
            "mjpython not found next to the interpreter; the MuJoCo viewer window "
            "won't open on macOS. Set CORAL_NO_VIEWER=1 to silence this."
        )
        return
    argv = sys.argv if sys.argv and Path(sys.argv[0]).exists() else ["-m", "coral_agent.collision.leg_bucket_test"]
    os.environ["CORAL_MJPYTHON"] = "1"
    logger.info("macOS: re-launching under mjpython so the MuJoCo viewer window opens...")
    os.execv(str(mjpython), [str(mjpython), *argv])


class _DynamicsModel:
    """MuJoCo model driven through its position actuators under real physics
    (gravity + floor contact) — measures where the robot actually settles for
    a given full-body joint target, not just where forward kinematics places
    it. Separate from CollisionChecker, which is intentionally kinematic-only
    (no integration) for cheap per-waypoint self-collision checks.

    Owns its own model/data so a viewer can be launched against them directly
    (see main()) and watch each settle happen live.
    """

    def __init__(self, model_path: str | None = None):
        if model_path is None:
            # leg_bucket_test.py lives at src/coral_agent/collision/ — four
            # levels up from the project root.
            project_root = Path(__file__).parent.parent.parent.parent
            model_path = str(project_root / "assets" / "ainex" / "ainex.xml")

        self.model = mujoco.MjModel.from_xml_path(model_path)
        self.data = mujoco.MjData(self.model)
        self.dt = float(self.model.opt.timestep)
        self.settle_steps = max(1, round(_SETTLE_SECONDS / self.dt))

        self._qpos_addr: dict[str, int] = {}
        self._actuator_id: dict[str, int] = {}
        for i in range(self.model.njnt):
            name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_JOINT, i)
            if name and self.model.jnt_type[i] == mujoco.mjtJoint.mjJNT_HINGE:
                self._qpos_addr[name] = int(self.model.jnt_qposadr[i])
                act_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_ACTUATOR, f"{name}_act")
                if act_id >= 0:
                    self._actuator_id[name] = act_id

        self._head_body_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, _HEAD_BODY_NAME)
        if self._head_body_id < 0:
            raise RuntimeError(f"body '{_HEAD_BODY_NAME}' not found in {model_path}")

        self._stand_joints = self._read_stand_keyframe()

    def _read_stand_keyframe(self) -> dict[str, float]:
        key_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_KEY, "stand")
        mujoco.mj_resetDataKeyframe(self.model, self.data, key_id)
        return {name: float(self.data.qpos[addr]) for name, addr in self._qpos_addr.items()}

    def stand_joints(self) -> dict[str, float]:
        return dict(self._stand_joints)

    def settle(
        self,
        joint_overrides: dict[str, float] | None = None,
        viewer: mujoco.viewer.Handle | None = None,
    ) -> dict:
        """Reset to the stand keyframe, drive every joint's actuator toward
        stand (overridden per `joint_overrides`), step physics forward under
        gravity+contact for `_SETTLE_SECONDS`, then read back head height and
        whole-body COM.

        If `viewer` is an open handle (launched against self.model/self.data in
        main()), syncs it periodically during settling so the motion is visible
        live, then holds the final result on screen for `_HOLD_SECONDS`.
        """
        key_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_KEY, "stand")
        mujoco.mj_resetDataKeyframe(self.model, self.data, key_id)  # qpos, qvel, ctrl all reset

        targets = dict(self._stand_joints)
        if joint_overrides:
            targets.update(joint_overrides)
        for name, val in targets.items():
            act_id = self._actuator_id.get(name)
            if act_id is not None:
                self.data.ctrl[act_id] = val

        live = viewer is not None and viewer.is_running()
        for step in range(self.settle_steps):
            mujoco.mj_step(self.model, self.data)
            if live and step % _VIEWER_SYNC_EVERY_N_STEPS == 0:
                viewer.sync()
                time.sleep(self.dt * _VIEWER_SYNC_EVERY_N_STEPS)

        if live:
            viewer.sync()
            time.sleep(_HOLD_SECONDS)

        head_z = float(self.data.xpos[self._head_body_id][2])
        # subtree_com[0]: COM of the whole kinematic tree rooted at the world
        # body (body 0) — i.e. the entire model's center of mass.
        com = self.data.subtree_com[0].copy()
        return {"head_z": head_z, "com": (float(com[0]), float(com[1]), float(com[2]))}


def run_leg_bucket_test(
    dyn: "_DynamicsModel | None" = None,
    checker: CollisionChecker | None = None,
    viewer: mujoco.viewer.Handle | None = None,
) -> dict:
    """Run all 27 (knee_ankle x hip_yaw_l x hip_yaw_r) combinations.

    Pass an existing `dyn`/`checker` to reuse their live mjData — e.g. so a
    viewer launched against dyn.model/dyn.data (see main()) shows each combo
    settling live. Without them, builds fresh headless instances.
    """
    if dyn is None:
        dyn = _DynamicsModel()
    if checker is None:
        checker = CollisionChecker()
    stand_joints = dyn.stand_joints()

    baseline = dyn.settle(viewer=viewer)
    stand_head_z = baseline["head_z"]
    logger.info(
        f"stand (settled {_SETTLE_SECONDS}s): head_z={stand_head_z:.4f} "
        f"com=({baseline['com'][0]:+.4f}, {baseline['com'][1]:+.4f})"
    )

    combos = [
        (ka, hy_l, hy_r)
        for ka in KNEE_ANKLE_BUCKETS
        for hy_l in HIP_YAW_BUCKETS
        for hy_r in HIP_YAW_BUCKETS
    ]

    results = []
    for knee_ankle_bucket, hip_yaw_l_bucket, hip_yaw_r_bucket in combos:
        leg_targets = combine_bucket_targets(knee_ankle_bucket, hip_yaw_l_bucket, hip_yaw_r_bucket)

        m = dyn.settle(leg_targets, viewer=viewer)
        head_z = m["head_z"]
        head_drop_frac = (stand_head_z - head_z) / stand_head_z if stand_head_z else 0.0
        fall_risk = head_drop_frac > _HEAD_DROP_FALL_THRESHOLD_FRAC

        com_x, com_y, com_z = m["com"]
        com_dev_from_origin = (com_x ** 2 + com_y ** 2) ** 0.5

        # Kinematic self-collision check on the commanded (unsettled) targets —
        # a correlated signal, not the same thing as the settled-physics result.
        safe_joints, safe_fraction, bad_pairs = checker.check_trajectory(stand_joints, leg_targets)
        collided = safe_fraction < 1.0

        label = f"{knee_ankle_bucket}/{hip_yaw_l_bucket}/{hip_yaw_r_bucket}"
        logger.info(
            f"{label:20s} head_z={head_z:.4f} (drop={head_drop_frac:+.1%}"
            f"{' FALL RISK' if fall_risk else ''}) "
            f"com=({com_x:+.4f}, {com_y:+.4f}) dev={com_dev_from_origin:.4f} "
            f"collision={'COLLISION' if collided else 'clear'}"
        )

        results.append({
            "knee_ankle_bucket": knee_ankle_bucket,
            "hip_yaw_l_bucket": hip_yaw_l_bucket,
            "hip_yaw_r_bucket": hip_yaw_r_bucket,
            "head_z": round(head_z, 5),
            "stand_head_z": round(stand_head_z, 5),
            "head_drop_frac": round(head_drop_frac, 5),
            "fall_risk": fall_risk,
            "com": {"x": round(com_x, 5), "y": round(com_y, 5), "z": round(com_z, 5)},
            "com_deviation_from_origin": round(com_dev_from_origin, 5),
            "collision": {
                "collided": collided,
                "safe_fraction": safe_fraction,
                "bad_pairs": bad_pairs,
            },
            "leg_targets": {k: round(v, 4) for k, v in leg_targets.items()},
        })

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "head_body": _HEAD_BODY_NAME,
        "settle_seconds": _SETTLE_SECONDS,
        "head_drop_fall_threshold_frac": _HEAD_DROP_FALL_THRESHOLD_FRAC,
        "stand_head_z": round(stand_head_z, 5),
        "stand_com": {"x": round(baseline["com"][0], 5), "y": round(baseline["com"][1], 5)},
        "any_fall_risk": any(r["fall_risk"] for r in results),
        "any_collision": any(r["collision"]["collided"] for r in results),
        "combos": results,
    }


def main() -> None:
    """Entry point: run all 27 combos, print a summary, and save a JSON report.

    Opens the native MuJoCo viewer by default so you can watch each combo
    settle live (holds it open after the run until you close the window). On
    macOS this needs `mjpython`, so the process re-execs under it
    automatically. Set CORAL_NO_VIEWER=1 for a headless run (e.g. CI).

    An optional CLI arg overrides the output path; the default lands in
    ``data/leg_bucket_test_report.json`` next to the pose database.
    """
    _reexec_under_mjpython_if_needed()

    dyn = _DynamicsModel()
    checker = CollisionChecker()
    viewer: mujoco.viewer.Handle | None = None
    if os.environ.get("CORAL_NO_VIEWER") != "1":
        try:
            viewer = mujoco.viewer.launch_passive(dyn.model, dyn.data)
            logger.info("MuJoCo viewer window opened")
        except Exception as e:
            logger.warning(f"Native viewer unavailable ({e}); running headless")

    report = run_leg_bucket_test(dyn, checker, viewer)

    out_arg = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
    if out_arg:
        out_path = Path(out_arg)
    else:
        out_path = Path(__file__).parent.parent.parent.parent / "data" / "leg_bucket_test_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    logger.info(
        f"Leg bucket test complete — "
        f"fall_risk={'YES' if report['any_fall_risk'] else 'no'}, "
        f"collision={'YES' if report['any_collision'] else 'no'}. "
        f"Report saved to {out_path}"
    )

    if viewer is not None:
        logger.info("Viewer open — close the window to exit.")
        while viewer.is_running():
            viewer.sync()
            time.sleep(0.1)
        viewer.close()


if __name__ == "__main__":
    main()
