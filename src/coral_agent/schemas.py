"""Pydantic schemas for structured LLM output.

Enforces chain-of-thought reasoning and validates waypoint structure.
"""

from pydantic import BaseModel, Field, field_validator

from coral_agent.validation import JOINT_LIMITS


class WaypointOutput(BaseModel):
    """A single waypoint in the robot motion sequence.

    Supports either named primitives OR raw joint values.
    """

    reasoning: str = Field(
        ...,
        description="Brief explanation of why these joints/this primitive was chosen",
        min_length=5,
    )
    primitive: str | None = Field(
        default=None,
        description="Name of a predefined motion primitive (e.g., 't_pose', 'wave_right')",
    )
    joints: dict[str, float] | None = Field(
        default=None,
        description="Raw joint values if no primitive is used",
    )
    speed: float = Field(
        default=1.0,
        ge=0.1,
        le=5.0,
        description="Movement speed multiplier (0.5=slow, 1.0=normal, 2.0+=fast)",
    )

    @field_validator("joints")
    @classmethod
    def validate_joints(cls, v: dict[str, float] | None) -> dict[str, float] | None:
        """Validate joint names exist in the known joints."""
        if v is None:
            return v

        for joint_name in v:
            if joint_name not in JOINT_LIMITS:
                # Allow unknown joints but log warning (handled in validation.py)
                pass

        return v

    def model_post_init(self, __context) -> None:
        """Ensure either primitive or joints is specified."""
        if self.primitive is None and self.joints is None:
            raise ValueError("Either 'primitive' or 'joints' must be specified")
        if self.primitive is not None and self.joints is not None:
            raise ValueError("Specify either 'primitive' or 'joints', not both")


class LLMResponse(BaseModel):
    """Complete structured response from the LLM.

    Enforces chain-of-thought reasoning before action.
    """

    thought_process: str = Field(
        ...,
        description="Step-by-step reasoning about what the user wants and how to achieve it",
        min_length=10,
    )
    waypoints: list[WaypointOutput] = Field(
        default_factory=list,
        description="Sequence of waypoints to execute (can be empty for conversational responses)",
    )
    verbal_response: str = Field(
        ...,
        description="Short verbal response to speak to the user",
        min_length=1,
    )


class RollbackCommand(BaseModel):
    """Detected rollback/undo command from user."""

    command_type: str = Field(
        ...,
        description="Type of rollback: 'undo', 'go_back', 'try_again', 'reset'",
    )
    steps: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Number of steps to roll back",
    )


# Example of valid LLM output for documentation/prompting
EXAMPLE_RESPONSE = {
    "thought_process": "User wants a T-pose. This requires both arms extended horizontally. "
    "For left arm outward: positive l_shoulder_aa. For right arm outward: negative r_shoulder_aa. "
    "Both shoulder_fe should be slightly negative to lift arms to horizontal.",
    "waypoints": [
        {
            "reasoning": "T-pose: both arms extended horizontally, elbows straight",
            "primitive": "t_pose",
            "speed": 1.0,
        }
    ],
    "verbal_response": "Moving to T-pose position.",
}

EXAMPLE_RAW_JOINTS = {
    "thought_process": "User wants to raise just the right arm forward. "
    "This uses r_shoulder_fe with a negative value to raise arm forward.",
    "waypoints": [
        {
            "reasoning": "Raise right arm forward by rotating shoulder",
            "joints": {"r_shoulder_fe": -1.0, "r_elbow": 0.0},
            "speed": 1.0,
        }
    ],
    "verbal_response": "Raising right arm forward.",
}
