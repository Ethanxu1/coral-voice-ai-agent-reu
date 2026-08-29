"""Pydantic response models and shared schemas for the Coral API."""

from pydantic import BaseModel


class CommandResponse(BaseModel):
    """Response for command execution."""

    success: bool
    message: str
    joint_states: dict[str, float] | None = None
