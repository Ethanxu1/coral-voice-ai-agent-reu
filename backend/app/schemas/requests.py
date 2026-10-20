"""Pydantic request models for the Coral API."""

from typing import Annotated

from pydantic import BaseModel, Field


class ServoMove(BaseModel):
    servo_id: int
    position: int
    duration_ms: int


class MoveRequest(BaseModel):
    moves: list[ServoMove]


class SetPoseRequest(BaseModel):
    """A raw pose as {joint_name: hardware_pulse} (the motions.py format)."""

    pulses: dict[str, Annotated[int, Field(ge=0, le=1000)]]
    # Pose Tester's "collision check off" mode: apply the pose exactly as
    # authored, skipping the collision/fall gate (joint limits still clamp).
    skip_collision_check: bool = False
    # 0 applies instantly; otherwise the sim glides there over this many ms.
    duration_ms: int = Field(default=0, ge=0, le=10000)


class IntentRequest(BaseModel):
    text: str
    follow_active: bool = False
    history: list[dict] | None = None  # [{"role": "user"|"assistant", "content": str}, ...]
    session_id: str | None = None


class SaveCurrentPoseRequest(BaseModel):
    name: str


class PlayPoseRequest(BaseModel):
    name: str
    duration_ms: int = 1000
    # None (the frontend's default — it doesn't send this field) means
    # "demonstrate": reaches hardware whenever the backend is connected to
    # it, regardless of the composing-only sim/hardware toggle. A caller can
    # still force sim-only (True) or force hardware (False) explicitly.
    sim_only: bool | None = None


class ExtractNameRequest(BaseModel):
    text: str
