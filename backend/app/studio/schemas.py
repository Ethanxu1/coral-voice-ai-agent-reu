"""Pydantic API and versioned project-package schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StudioModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectSettings(StudioModel):
    output_mode: Literal["simulator", "live_robot"] = "simulator"


class ProjectPayload(StudioModel):
    id: str
    name: str
    schema_version: int = 1
    created_at: str
    updated_at: str


class HumanPosePayload(StudioModel):
    id: str
    project_id: str
    name: str
    thumbnail_svg: str = ""
    min_confidence: float = Field(ge=0, le=1)
    hold_seconds: float = Field(gt=0, le=10)
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""


class PoseSamplePayload(StudioModel):
    id: str
    human_pose_id: str
    features: list[float]
    weights: list[float]
    mirror_metadata: dict[str, Any] = Field(default_factory=dict)
    quality: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""


class RobotPosePayload(StudioModel):
    id: str
    project_id: str
    name: str
    joints: dict[str, float]
    thumbnail_svg: str = ""
    source: str = "simulator"
    safety: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


class SequenceStepPayload(StudioModel):
    id: str
    robot_pose_id: str
    position: int = Field(ge=0)
    hold_ms: int = Field(ge=0, le=60_000)
    transition_ms: int = Field(gt=0, le=60_000)


class SequencePayload(StudioModel):
    id: str
    project_id: str
    name: str
    steps: list[SequenceStepPayload]
    created_at: str = ""
    updated_at: str = ""


class BehaviorRulePayload(StudioModel):
    id: str
    project_id: str
    human_pose_id: str
    sequence_id: str
    cooldown_seconds: float = Field(ge=0, le=300)
    priority: int = 0
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""


class ProjectPackage(StudioModel):
    schema_version: Literal[1]
    project: ProjectPayload
    human_poses: list[HumanPosePayload]
    training_samples: list[PoseSamplePayload]
    robot_poses: list[RobotPosePayload]
    sequences: list[SequencePayload]
    rules: list[BehaviorRulePayload]
    settings: ProjectSettings = Field(default_factory=ProjectSettings)


class CreateProjectRequest(StudioModel):
    name: str = Field(min_length=1, max_length=120)


class CreateHumanPoseRequest(StudioModel):
    project_id: str
    name: str = Field(min_length=1, max_length=120)
    min_confidence: float = Field(default=0.78, ge=0, le=1)
    hold_seconds: float = Field(default=0.7, gt=0, le=10)
    thumbnail_svg: str = ""


class CreatePoseSampleRequest(StudioModel):
    landmarks: list[dict[str, float]]


class CreateRobotPoseRequest(StudioModel):
    project_id: str
    name: str = Field(min_length=1, max_length=120)
    joints: dict[str, float]
    thumbnail_svg: str = ""
    source: Literal["human", "simulator"] = "simulator"
    safety: dict[str, Any] = Field(default_factory=dict)


class CreateSequenceStepRequest(StudioModel):
    robot_pose_id: str
    hold_ms: int = Field(default=500, ge=0, le=60_000)
    transition_ms: int = Field(default=250, gt=0, le=60_000)


class CreateSequenceRequest(StudioModel):
    project_id: str
    name: str = Field(min_length=1, max_length=120)
    steps: list[CreateSequenceStepRequest]


class UpdateSequenceRequest(StudioModel):
    name: str = Field(min_length=1, max_length=120)
    steps: list[CreateSequenceStepRequest]


class CreateRuleRequest(StudioModel):
    project_id: str
    human_pose_id: str
    sequence_id: str
    cooldown_seconds: float = Field(default=2.0, ge=0, le=300)
    priority: int = 0
    enabled: bool = True


class ReorderInteractionsRequest(StudioModel):
    project_id: str
    rule_ids: list[str]


class OutputModeRequest(StudioModel):
    mode: Literal["simulator", "live_robot"]


class TriggerModeRequest(StudioModel):
    enabled: bool
