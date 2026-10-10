"""Typed domain records stored by Motion Block Studio."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    name: str
    schema_version: int
    settings: dict[str, Any]
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class HumanPose:
    id: str
    project_id: str
    name: str
    thumbnail_svg: str
    min_confidence: float
    hold_seconds: float
    enabled: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class PoseSample:
    id: str
    human_pose_id: str
    features: list[float]
    weights: list[float]
    mirror_metadata: dict[str, Any]
    quality: dict[str, Any]
    created_at: str


@dataclass(frozen=True, slots=True)
class RobotPose:
    id: str
    project_id: str
    name: str
    joints: dict[str, float]
    thumbnail_svg: str
    source: str
    safety: dict[str, Any]
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class SequenceStep:
    id: str
    sequence_id: str
    robot_pose_id: str
    position: int
    hold_ms: int
    transition_ms: int


@dataclass(frozen=True, slots=True)
class Sequence:
    id: str
    project_id: str
    name: str
    steps: tuple[SequenceStep, ...]
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class BehaviorRule:
    id: str
    project_id: str
    human_pose_id: str
    sequence_id: str
    cooldown_seconds: float
    priority: int
    enabled: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class DeleteResult:
    deleted: bool
    dependents: list[str]
