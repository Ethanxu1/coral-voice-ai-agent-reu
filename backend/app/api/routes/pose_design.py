"""Pose Designer routes: one conversation turn, the "save this pose" check, and the ghost preview."""

from typing import Any

from app.robot.hardware_angle_utils import hardware_units_to_rad
from app.schemas.requests import PoseDesignTurnRequest, PosePreviewRequest, SaveCommandRequest
from app.services.pose_design import (
    CANT_MOVE_REPLY,
    CONTROLS,
    apply_changes,
    design_turn,
    is_save_command,
    merge_changes,
    reachable_changes,
    strip_wake_word,
)
from app.state import state
from fastapi import APIRouter, HTTPException
from loguru import logger

router = APIRouter()


@router.post("/pose-design/turn")
async def pose_design_turn(req: PoseDesignTurnRequest) -> dict[str, Any]:
    """What the child wants done to the pose. Moves nothing: for a proposal it
    returns the proposed pose, which the page previews and applies only once
    the child accepts. The wake word ("hey CORAL") is stripped; alone it is a
    `wake` (the page starts listening for the request). Without it, a turn that
    `needs_wake_word` is `ignore`d. Neither asks the LLM."""
    unknown = set(req.proposal) - set(CONTROLS)
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown controls: {sorted(unknown)}")
    rest = strip_wake_word(req.text)
    if rest == "" or (rest is None and req.needs_wake_word):
        return {"action": "wake" if rest == "" else "ignore", "reply": "", "changes": [], "proposed_pulses": None}
    text = req.text if rest is None else rest
    turn = await design_turn(text, req.pulses, req.proposal, [t.model_dump() for t in req.history])
    action, reply, changes = turn.action, turn.reply, {}
    if action == "propose":
        changes = reachable_changes(req.pulses, merge_changes(turn.changes))
        if not changes:
            action, reply = "chat", CANT_MOVE_REPLY
    logger.info(f"pose design: {text!r} -> {action} {changes}")
    return {
        "action": action,
        "reply": reply,
        "changes": [
            {"control": name, "label": CONTROLS[name].label, "degrees": round(deg)}
            for name, deg in changes.items()
        ],
        "proposed_pulses": apply_changes(req.pulses, changes) if changes else None,
    }


@router.post("/pose-design/save-command")
async def pose_design_save_command(req: SaveCommandRequest) -> dict[str, bool]:
    """Whether the child said to keep the pose CORAL is following them into
    ("save this pose", "freeze!"). Regex only, so it answers at once."""
    return {"save": is_save_command(req.text)}


@router.post("/pose-design/preview")
async def pose_design_preview(req: PosePreviewRequest) -> dict[str, list[float]]:
    """Every render geom's world pose (the /ws/sim frame layout) with the robot
    as it stands now but these joints set, for drawing a ghost of the pose."""
    if state.simulator is None:
        raise HTTPException(status_code=503, detail="simulator not initialized")
    joints = {
        name: hardware_units_to_rad(pulse, name)
        for name, pulse in req.pulses.items()
        if name in state.simulator.JOINT_NAMES
    }
    buf = state.simulator.get_geom_poses(preview=joints)
    return {"poses": memoryview(buf).cast("f").tolist()}
