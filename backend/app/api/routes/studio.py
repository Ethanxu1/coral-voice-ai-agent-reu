"""Motion Block Studio HTTP resources and live event WebSocket."""

from __future__ import annotations

import json
import math

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from app.robot.servo_config import SERVO_ID_MAP
from app.services.motion import validate_motion_path
from app.state import state
from app.studio.features import extract_pose_features, render_skeleton_svg, validate_training_sample
from app.studio.import_export import PackageValidationError, export_package, import_package
from app.studio.repository import StudioRepository
from app.studio.runtime import StudioRuntime
from app.studio.schemas import (
    CreateHumanPoseRequest,
    CreatePoseSampleRequest,
    CreateProjectRequest,
    CreateRobotPoseRequest,
    CreateRuleRequest,
    CreateSequenceRequest,
    OutputModeRequest,
    ProjectPackage,
    ReorderInteractionsRequest,
    TriggerModeRequest,
    UpdateSequenceRequest,
)
from app.studio.sequence_player import OutputMode

MAX_IMPORT_BYTES = 5 * 1024 * 1024
router = APIRouter(prefix="/studio", tags=["studio"])
_repository: StudioRepository | None = None
_runtime: StudioRuntime | None = None


def configure_studio(repository: StudioRepository, runtime: StudioRuntime) -> None:
    global _repository, _runtime
    _repository = repository
    _runtime = runtime


def _repo() -> StudioRepository:
    if _repository is None:
        raise HTTPException(status_code=503, detail="Studio is not initialized")
    return _repository


def _studio_runtime() -> StudioRuntime:
    if _runtime is None:
        raise HTTPException(status_code=503, detail="Studio is not initialized")
    return _runtime


@router.get("/projects")
def list_projects():
    return jsonable_encoder(_repo().list_projects())


@router.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project(request: CreateProjectRequest):
    try:
        return jsonable_encoder(_repo().create_project(request.name.strip()))
    except Exception as exc:
        _translate_integrity_error(exc)


@router.get("/projects/{project_id}/export")
def export_project(project_id: str):
    try:
        return export_package(_repo(), project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.post("/projects/import", status_code=status.HTTP_201_CREATED)
async def import_project(request: Request):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="Project package exceeds 5 MiB")
    body = await request.body()
    if len(body) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="Project package exceeds 5 MiB")
    try:
        package = ProjectPackage.model_validate(json.loads(body))
        project_id = import_package(_repo(), package)
    except (json.JSONDecodeError, ValidationError, PackageValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _studio_runtime().refresh_recognizer()
    return {"project_id": project_id}


@router.get("/human-poses")
def list_human_poses(project_id: str):
    return jsonable_encoder(_repo().list_human_poses(project_id))


@router.post("/human-poses", status_code=status.HTTP_201_CREATED)
def create_human_pose(request: CreateHumanPoseRequest):
    try:
        pose = _repo().create_human_pose(
            request.project_id,
            request.name.strip(),
            request.min_confidence,
            request.hold_seconds,
            thumbnail_svg=request.thumbnail_svg,
        )
        return jsonable_encoder(pose)
    except Exception as exc:
        _translate_integrity_error(exc)


@router.post("/human-poses/{pose_id}/samples", status_code=status.HTTP_201_CREATED)
def create_pose_sample(pose_id: str, request: CreatePoseSampleRequest):
    quality = validate_training_sample(request.landmarks)
    if not quality.accepted:
        raise HTTPException(status_code=422, detail=quality.message)
    features = extract_pose_features(request.landmarks)
    sample = _repo().create_pose_sample(
        pose_id,
        features.values,
        features.weights,
        quality=jsonable_encoder(quality),
    )
    _studio_runtime().refresh_recognizer()
    return {
        **jsonable_encoder(sample),
        "thumbnail_svg": render_skeleton_svg(request.landmarks),
    }


@router.get("/robot-poses")
def list_robot_poses(project_id: str):
    return jsonable_encoder(_repo().list_robot_poses(project_id))


@router.post("/robot-poses", status_code=status.HTTP_201_CREATED)
def create_robot_pose(request: CreateRobotPoseRequest):
    unknown = set(request.joints) - set(SERVO_ID_MAP)
    if unknown or not all(math.isfinite(value) for value in request.joints.values()):
        raise HTTPException(status_code=422, detail="Robot pose contains invalid joints")
    safety = validate_motion_path(
        state.simulator,
        [request.joints],
        "studio robot pose capture",
    )
    if not safety.safe:
        raise HTTPException(
            status_code=422,
            detail={"reason": safety.reason, "failed_step": safety.failed_step},
        )
    pose = _repo().create_robot_pose(
        request.project_id,
        request.name.strip(),
        request.joints,
        thumbnail_svg=request.thumbnail_svg,
        source=request.source,
        safety={"safe": True, "reports": list(safety.reports)},
    )
    return jsonable_encoder(pose)


@router.post("/robot-poses/{pose_id}/preview")
async def preview_robot_pose(pose_id: str):
    try:
        result = await _studio_runtime().preview_pose(pose_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Robot pose not found") from exc
    return jsonable_encoder(result)


@router.get("/sequences")
def list_sequences(project_id: str):
    return jsonable_encoder(_repo().list_sequences(project_id))


@router.post("/sequences", status_code=status.HTTP_201_CREATED)
def create_sequence(request: CreateSequenceRequest):
    sequence = _repo().create_sequence(
        request.project_id,
        request.name.strip(),
        [step.model_dump() for step in request.steps],
    )
    return jsonable_encoder(sequence)


@router.post("/sequences/{sequence_id}/preview")
async def preview_sequence(sequence_id: str):
    return jsonable_encoder(await _studio_runtime().preview(sequence_id))


@router.put("/sequences/{sequence_id}")
def update_sequence(sequence_id: str, request: UpdateSequenceRequest):
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Sequence name is required")
    try:
        sequence = _repo().update_sequence(
            sequence_id,
            name,
            [step.model_dump() for step in request.steps],
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Sequence not found") from exc
    except Exception as exc:
        _translate_integrity_error(exc)
    return jsonable_encoder(sequence)


@router.delete("/sequences/{sequence_id}")
def delete_sequence(sequence_id: str):
    result = _repo().delete_sequence(sequence_id)
    if not result.deleted and result.dependents:
        raise HTTPException(status_code=409, detail={"dependents": result.dependents})
    if not result.deleted:
        raise HTTPException(status_code=404, detail="Sequence not found")
    return {"deleted": True}


@router.get("/rules")
def list_rules(project_id: str):
    return jsonable_encoder(_repo().list_behavior_rules(project_id))


@router.post("/rules", status_code=status.HTTP_201_CREATED)
def create_rule(request: CreateRuleRequest):
    rule = _repo().create_behavior_rule(**request.model_dump())
    return jsonable_encoder(rule)


@router.put("/interactions/order")
def reorder_interactions(request: ReorderInteractionsRequest):
    try:
        _repo().reorder_interactions(request.project_id, request.rule_ids)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"reordered": True}


@router.delete("/interactions/{rule_id}")
def delete_interaction(rule_id: str):
    try:
        deleted = _repo().delete_interaction(rule_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Interaction not found")
    return {"deleted": True}


@router.delete("/robot-poses/{pose_id}")
def delete_robot_pose(pose_id: str):
    result = _repo().delete_robot_pose(pose_id)
    if not result.deleted and result.dependents:
        raise HTTPException(status_code=409, detail={"dependents": result.dependents})
    if not result.deleted:
        raise HTTPException(status_code=404, detail="Robot pose not found")
    return {"deleted": True}


@router.delete("/human-poses/{pose_id}")
def delete_human_pose(pose_id: str):
    result = _repo().delete_human_pose(pose_id)
    if not result.deleted and result.dependents:
        raise HTTPException(status_code=409, detail={"dependents": result.dependents})
    if not result.deleted:
        raise HTTPException(status_code=404, detail="Human pose not found")
    _studio_runtime().refresh_recognizer()
    return {"deleted": True}


@router.get("/output-mode")
def get_output_mode():
    return {"mode": _studio_runtime().output_mode.value}


@router.put("/output-mode")
async def set_output_mode(request: OutputModeRequest):
    mode = await _studio_runtime().set_output_mode(OutputMode(request.mode))
    return {"mode": mode.value}


@router.get("/trigger-mode")
def get_trigger_mode():
    return {"enabled": _studio_runtime().trigger_enabled}


@router.put("/trigger-mode")
def set_trigger_mode(request: TriggerModeRequest):
    return {"enabled": _studio_runtime().set_trigger_enabled(request.enabled)}


@router.websocket("/ws")
async def studio_events(websocket: WebSocket):
    await websocket.accept()
    runtime = _studio_runtime()
    queue = runtime.subscribe()
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event.to_dict())
    except WebSocketDisconnect:
        pass
    finally:
        runtime.unsubscribe(queue)


def _translate_integrity_error(exc: Exception) -> None:
    message = str(exc).lower()
    if "unique" in message:
        raise HTTPException(status_code=409, detail="Name already exists") from exc
    if "foreign key" in message:
        raise HTTPException(status_code=422, detail="Referenced resource not found") from exc
    raise exc
