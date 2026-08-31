"""Typed intent schemas for the CORAL voice pipeline.

These models are the single source of truth for:
- Regex classifier output
- LLM structured-output parsing
- API responses from /classify-intent
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field


class BaseIntent(BaseModel):
    """Common fields every intent response carries.

    ``type`` is required so the discriminated-union parser can route to the
    right shape. ``classifier`` and ``reason`` are added by the classifier
    code after parsing; the LLM does not need to emit them.
    """

    type: str
    classifier: Literal["regex", "llm"] = "llm"
    reason: str = ""


class ImmediateIntent(BaseIntent):
    """System-level commands that don't need motion planning."""

    type: Literal["immediate"]
    intent: Literal[
        "follow_start",
        "follow_stop",
        "capture",
        "play_pose",
        "library",
        "exit",
        "save_robot_pose",
        "naming",
        "undo",
        "reset",
        "rollback_and_retry",
    ]
    name: Optional[str] = None


class MotionIntent(BaseIntent):
    """A concrete, executable movement request."""

    type: Literal["motion"]
    description: str = Field(..., min_length=1)
    # Optional parsed metadata that the classifier or LLM may fill in.
    direction: Optional[Literal["left", "right", "up", "down", "in", "out"]] = None
    angle: Optional[float] = None
    body_parts: list[str] = Field(default_factory=list)


class ClarificationIntent(BaseIntent):
    """A specific follow-up question when the user's request is ambiguous."""

    type: Literal["clarification"]
    question: str = Field(..., min_length=1)


class ConversationIntent(BaseIntent):
    """General chat, questions, or comments that don't require motion."""

    type: Literal["conversation"]
    text: str = Field(..., min_length=1)


Intent = Annotated[
    ImmediateIntent | MotionIntent | ClarificationIntent | ConversationIntent,
    Field(discriminator="type"),
]
