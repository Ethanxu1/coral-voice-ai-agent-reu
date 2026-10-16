"""Motion, pose, and saved-pose API routes."""

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from langfuse.openai import openai
from loguru import logger

from app.data.pose_db import get_pose, list_pose_names, save_pose
from app.llm.config import LLM_MODEL
from app.robot.angle_utils import rad_to_servo_units, servo_units_to_rad
from app.robot.hardware_angle_utils import hardware_units_to_rad
from app.robot.interface import ServoCommand
from app.robot.servo_config import JOINT_NAME_MAP, SERVO_ID_MAP
from app.schemas.requests import (
    ExtractNameRequest,
    MoveRequest,
    PlayPoseRequest,
    SaveCurrentPoseRequest,
    SetPoseRequest,
)
from app.services.motion import (
    RESET_TO_STAND_MS,
    RobotServerUnavailable,
    _execute_on_hardware_if_connected,
    _get_robot_state,
    collision_checked_targets,
    dispatch_servo_commands,
)
from app.state import state

router = APIRouter()

_NAME_PROMPT_PATH = Path(__file__).parent.parent.parent / "llm" / "prompts" / "name_extraction.md"
_NAME_SANITIZE_RE = re.compile(r"[^\w\s\-]")
_LIVE_LEG_JOINTS = {
    "l_hip_yaw", "l_hip_roll", "l_hip_pitch", "l_knee", "l_ank_pitch", "l_ank_roll",
    "r_hip_yaw", "r_hip_roll", "r_hip_pitch", "r_knee", "r_ank_pitch", "r_ank_roll",
}
_LIVE_MIRROR_JOINTS = set(SERVO_ID_MAP)
_MAX_LIVE_JOINT_STEP_RAD = 0.08
_SIM_MOTION_LOCK = asyncio.Lock()


def _sanitize_name(raw: str) -> str:
    return _NAME_SANITIZE_RE.sub("", raw).strip()


def _load_name_extraction_prompt() -> str:
    if _NAME_PROMPT_PATH.exists():
        return _NAME_PROMPT_PATH.read_text(encoding="utf-8")
    return (
        "Extract just the intended name from the child's naming answer, "
        "stripping filler like \"let's name it\". Respond with strict JSON: "
        '{"name": "<extracted name>"}.'
    )


def _limit_live_joint_step(
    current_joints: dict[str, float],
    target_joints: dict[str, float],
    limited_joints: set[str],
) -> tuple[dict[str, float], bool]:
    """Rate-limit selected simulator live-mirror joints to reduce tipping impulses."""
    limited = dict(target_joints)
    changed = False
    for joint in limited_joints.intersection(target_joints):
        current = current_joints.get(joint)
        if current is None:
            continue
        delta = target_joints[joint] - current
        if abs(delta) <= _MAX_LIVE_JOINT_STEP_RAD:
            continue
        limited[joint] = current + (1 if delta > 0 else -1) * _MAX_LIVE_JOINT_STEP_RAD
        changed = True
    return limited, changed


def _limit_live_leg_step(
    current_joints: dict[str, float],
    target_joints: dict[str, float],
) -> tuple[dict[str, float], bool]:
    """Keep the original leg-only live-mirror behavior for non-gentle callers."""
    return _limit_live_joint_step(current_joints, target_joints, _LIVE_LEG_JOINTS)


@router.post("/move")
async def demo_move(request: MoveRequest) -> dict[str, Any]:
    """Serialize Studio moves with resets so a stale move cannot win the race."""
    async with _SIM_MOTION_LOCK:
        return await _execute_demo_move(request)


async def _execute_demo_move(request: MoveRequest) -> dict[str, Any]:
    """Execute raw servo commands on the simulator, optionally with hardware.

    Used by the demo's pose-mimicry path: the frontend fetches servo commands
    from the vision server's /map-features (landmark retargeting) and posts them
    here to drive the robot.

    Landmark retargeting has no notion of self-collision, so before dispatch we
    shadow-roll the combined target through the collision checker and clamp any
    servo whose commanded pose would drive it into another link.

    Decodes with servo_units_to_rad (the uniform 500-centre sim map), not
    hardware_units_to_rad — /map-features always encodes with rad_to_servo_units,
    the same uniform map, regardless of sim/hardware mode.
    """
    if state.simulator is None:
        raise HTTPException(status_code=503, detail="simulation server is not initialized")
    if request.stabilized_preview and request.sim_only is not True:
        raise HTTPException(
            status_code=400,
            detail="stabilized preview is available only for simulator-only moves",
        )

    moves = request.moves
    target_joints = {
        joint: servo_units_to_rad(m.position)
        for m in moves
        if (joint := JOINT_NAME_MAP.get(m.servo_id)) is not None
    }
    rate_limited = False
    if request.sim_only is True and not request.stabilized_preview:
        limited_joints = _LIVE_MIRROR_JOINTS if request.gentle else _LIVE_LEG_JOINTS
        target_joints, rate_limited = _limit_live_joint_step(
            state.simulator.get_all_joint_states(),
            target_joints,
            limited_joints,
        )
    if request.stabilized_preview:
        state.simulator.enable_stabilized_preview(ttl_seconds=1.0)
        safety = {
            "fall_blocked": False,
            "collision_clamped": False,
            "rate_limited": False,
            "safe_fraction": 1.0,
            "bad_pairs": [],
            "head_z": None,
            "threshold_z": None,
        }
    else:
        transition_seconds = (
            max((max(100, move.duration_ms) for move in moves), default=100) / 1000
        )
        dynamics_state = (
            state.simulator.get_dynamics_state()
            if request.sim_only is True and request.gentle
            else None
        )
        target_joints, safety = collision_checked_targets(
            state.simulator,
            target_joints,
            "/move",
            transition_seconds=transition_seconds,
            dynamics_state=dynamics_state,
        )
        safety["rate_limited"] = rate_limited

    # Fall check failed → the move is unsafe as a whole. Dispatch nothing (0%
    # of the move) and let the caller report the blocked result to the user.
    if safety["fall_blocked"]:
        return {
            "status": "blocked",
            "count": 0,
            "targets": target_joints,
            "safety": safety,
        }

    commands = []
    for m in moves:
        joint = JOINT_NAME_MAP.get(m.servo_id)
        position = (
            rad_to_servo_units(target_joints[joint])
            if joint in target_joints
            else m.position
        )
        commands.append(
            ServoCommand(
                servo_id=m.servo_id,
                position=position,
                duration_ms=max(100, m.duration_ms),
            )
        )

    if state.sim_dispatcher is None:
        raise HTTPException(status_code=503, detail="simulation server is not initialized")

    try:
        await dispatch_servo_commands(commands, sim_only=request.sim_only)
    except RobotServerUnavailable as e:
        logger.warning(f"/move: robot server unavailable: {e}")
        raise HTTPException(status_code=503, detail="robot server could not be reached")
    return {
        "status": "done",
        "count": len(commands),
        "targets": target_joints,
        "safety": safety,
    }


@router.post("/set-pose")
async def set_pose(req: SetPoseRequest) -> dict[str, Any]:
    """Apply a raw {joint: hardware_pulse} pose to the sim (testing tool).

    Accepts the exact pulse dicts authored in motions.py. Each pulse is a
    *hardware* servo unit, so it's converted to sim radians with
    hardware_units_to_rad. The combined target is then shadow-rolled through the
    collision checker (same as /move) before set_joint_position applies it.
    Sim only; unknown joints are reported back.
    """
    if state.simulator is None:
        return {"status": "error", "detail": "simulator not initialized"}

    applied: list[str] = []
    skipped: list[str] = []

    target_joints: dict[str, float] = {}
    for joint, pulse in req.pulses.items():
        if joint not in SERVO_ID_MAP:
            skipped.append(joint)
            continue
        try:
            target_joints[joint] = hardware_units_to_rad(int(pulse), joint)
        except Exception as e:  # bad pulse value — skip, keep going
            logger.debug(f"/set-pose: skip joint {joint}: {e}")
            skipped.append(joint)

    if not req.skip_collision_check:
        target_joints, _safety = collision_checked_targets(
            state.simulator, target_joints, "/set-pose"
        )

    for joint, rad in target_joints.items():
        try:
            state.simulator.set_joint_position(joint, rad)
            applied.append(joint)
        except Exception as e:  # unknown sim joint — skip, keep going
            logger.debug(f"/set-pose: skip joint {joint}: {e}")
            skipped.append(joint)

    return {"status": "done", "applied": applied, "skipped": skipped}


@router.post("/reset")
async def reset_pose(sim_only: bool = False) -> dict[str, Any]:
    """Serialize reset after any in-flight move so standing is the final pose."""
    async with _SIM_MOTION_LOCK:
        return await _execute_reset_pose(sim_only)


async def _execute_reset_pose(sim_only: bool = False) -> dict[str, Any]:
    """Reset the sim to standing, optionally leaving hardware untouched."""
    if state.simulator is None:
        return {"status": "error", "detail": "simulator not initialized"}

    await asyncio.to_thread(state.simulator.reset_pose)

    if state.hardware_dispatcher is not None and not sim_only:
        stand = state.simulator.get_stand_joint_positions()
        commands = [
            ServoCommand(
                servo_id=sid,
                position=rad_to_servo_units(rad),
                duration_ms=RESET_TO_STAND_MS,
            )
            for joint, rad in stand.items()
            if (sid := SERVO_ID_MAP.get(joint)) is not None
        ]
        if commands:
            try:
                await dispatch_servo_commands(commands, sim_only=None)
            except RobotServerUnavailable as e:
                logger.warning(f"/reset: robot server unavailable: {e}")

    return {"status": "done"}


@router.get("/poses")
async def list_poses_endpoint() -> dict[str, list[str]]:
    """List all saved pose names."""
    names = list_pose_names()
    return {"poses": names}


@router.post("/poses/save-current")
async def save_current_pose_endpoint(req: SaveCurrentPoseRequest) -> dict[str, str]:
    """Save the current robot joint state under the given name."""
    joints = _get_robot_state()
    clean_name = req.name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    save_pose(clean_name, joints)
    await _execute_on_hardware_if_connected(joints)
    return {"name": clean_name, "status": "saved"}


@router.post("/poses/play")
async def play_pose_endpoint(req: PlayPoseRequest) -> dict[str, Any]:
    """Strike a saved pose directly by name, without the LLM motion planner."""
    clean_name = req.name.strip()
    joints = get_pose(clean_name)
    if joints is None:
        raise HTTPException(status_code=404, detail=f"Pose '{clean_name}' not found")
    joints, _safety = collision_checked_targets(
        state.simulator, joints, f"/poses/play '{clean_name}'"
    )
    duration_ms = max(1, req.duration_ms)
    commands = [
        ServoCommand(
            servo_id=SERVO_ID_MAP[joint],
            position=rad_to_servo_units(rad),
            duration_ms=duration_ms,
        )
        for joint, rad in joints.items()
        if joint in SERVO_ID_MAP
    ]
    await dispatch_servo_commands(commands, sim_only=req.sim_only)
    logger.info(f"Played saved pose '{clean_name}' ({len(commands)} joints)")
    return {"name": clean_name, "joints_played": len(commands), "status": "played"}


@router.post("/poses/extract-name")
async def extract_name_endpoint(req: ExtractNameRequest) -> dict[str, str]:
    """Extract a clean pose name from a child's free-form naming answer.

    Tries an LLM extraction (strips filler like "let's name it X" -> "X").
    On any LLM/parse failure, falls back to the sanitized verbatim input.
    Never raises for LLM problems -- only for empty input (400).
    """
    raw = req.text.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Name text cannot be empty")

    def call_llm() -> str:
        response = openai.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": _load_name_extraction_prompt()},
                {"role": "user", "content": raw},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "pose_name",
                    "schema": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                        "required": ["name"],
                        "additionalProperties": False,
                    },
                },
            },
            max_completion_tokens=30,
        )
        return response.choices[0].message.content or "{}"

    try:
        content = await asyncio.to_thread(call_llm)
        extracted = json.loads(content).get("name", "")
        name = _sanitize_name(extracted) or _sanitize_name(raw)
    except Exception as e:
        logger.warning(f"/poses/extract-name: LLM extraction failed, using sanitized verbatim: {e}")
        name = _sanitize_name(raw)

    return {"name": name}
