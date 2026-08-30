"""Typed motion-plan schema for the CORAL LLM motion planner.

The router LLM is constrained to emit JSON matching `MotionPlan`. This
replaces the previous unconstrained `json_object` parsing and guarantees
that every field is type-checked before it reaches the robot.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


PrimitiveName = Literal[
    "left_arm_out",
    "right_arm_out",
    "left_arm_forward",
    "right_arm_forward",
    "left_elbow_bend",
    "right_elbow_bend",
    "left_elbow_rotate",
    "right_elbow_rotate",
    "head_turn",
    "head_tilt",
    "neutral",
]

Direction = Literal["left", "right", "up", "down", "in", "out"]


class PlainWaypoint(BaseModel):
    """A single step that moves one or more primitives simultaneously."""

    model_config = ConfigDict(extra="forbid")

    primitives: list[PrimitiveName] = Field(..., min_length=1)
    angle: Optional[float] = None
    direction: Optional[Direction] = None
    speed: float = Field(1.0, ge=0.1, le=8.0)


class ParallelGroup(BaseModel):
    """Multiple sequential tracks that run concurrently."""

    model_config = ConfigDict(extra="forbid")

    parallel: list[list[PlainWaypoint]] = Field(..., min_length=1)


class MotionPlan(BaseModel):
    """Top-level response from the motion-planner LLM."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["motion", "execute_saved_pose"] = "motion"
    waypoints: list[PlainWaypoint | ParallelGroup] = Field(default_factory=list)
    verbal_response: str = ""
    satisfied: Optional[bool] = None
    # Only used when action == "execute_saved_pose".
    pose_name: Optional[str] = None
