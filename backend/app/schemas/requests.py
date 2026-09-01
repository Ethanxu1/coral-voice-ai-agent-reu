"""Pydantic request models for the Coral API."""

from pydantic import BaseModel


class ChatMessage(BaseModel):
    """Chat message structure."""

    role: str  # "user" or "assistant"
    content: str
    commands: list[str] | None = None


class ServoMove(BaseModel):
    servo_id: int
    position: int
    duration_ms: int


class MoveRequest(BaseModel):
    moves: list[ServoMove]


class SetPoseRequest(BaseModel):
    """A raw pose as {joint_name: hardware_pulse}, e.g. pasted from motions.py."""

    pulses: dict[str, int]
    # Pose Tester's "collision check off" mode: apply the pose exactly as
    # authored, skipping the collision shadow-roll (JOINT_LIMITS still clamp).
    skip_collision_check: bool = False


class StateRequest(BaseModel):
    mode: str


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
