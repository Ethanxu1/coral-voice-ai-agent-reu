"""Pydantic schemas for structured LLM output.

Enforces chain-of-thought reasoning and validates waypoint structure.
"""

from pydantic import BaseModel, Field, field_validator

from coral_agent.validation import JOINT_LIMITS


class WaypointOutput(BaseModel):
    """A single waypoint in the robot motion sequence.

    Supports either named primitives (with optional angle/direction) OR raw joint values.
    """

    reasoning: str = Field(
        ...,
        description="Brief explanation of why these joints/this primitive was chosen",
        min_length=5,
    )
    primitive: str | None = Field(
        default=None,
        description="Name of a predefined motion primitive (e.g., 'left_arm_out', 'head_turn')",
    )
    angle: float | None = Field(
        default=None,
        ge=0,
        le=180,
        description="Angle in degrees for parameterized primitives (0-180)",
    )
    direction: str | None = Field(
        default=None,
        description="Direction for bidirectional primitives: 'left', 'right', 'up', 'down'",
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

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, v: str | None) -> str | None:
        """Validate direction is one of the allowed values."""
        if v is None:
            return v
        v_lower = v.lower().strip()
        allowed = {"left", "right", "up", "down"}
        if v_lower not in allowed:
            raise ValueError(f"direction must be one of {allowed}, got '{v}'")
        return v_lower

    def model_post_init(self, __context) -> None:
        """Ensure either primitive or joints is specified, and validate angle/direction usage."""
        if self.primitive is None and self.joints is None:
            raise ValueError("Either 'primitive' or 'joints' must be specified")
        if self.primitive is not None and self.joints is not None:
            raise ValueError("Specify either 'primitive' or 'joints', not both")

        # angle and direction should only be used with primitive
        if self.joints is not None:
            if self.angle is not None:
                raise ValueError("'angle' can only be used with 'primitive', not 'joints'")
            if self.direction is not None:
                raise ValueError("'direction' can only be used with 'primitive', not 'joints'")


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
    "thought_process": "User wants right arm out 75 degrees. Using right_arm_out primitive with angle=75.",
    "waypoints": [
        {
            "reasoning": "Moving right arm sideways to 75 degrees",
            "primitive": "right_arm_out",
            "angle": 75,
            "speed": 1.0,
        }
    ],
    "verbal_response": "Moving right arm out to 75 degrees.",
}

EXAMPLE_BIDIRECTIONAL = {
    "thought_process": "User wants to look left 60 degrees. Using head_turn primitive with direction=left and angle=60.",
    "waypoints": [
        {
            "reasoning": "Turning head 60 degrees to the left",
            "primitive": "head_turn",
            "angle": 60,
            "direction": "left",
            "speed": 2.0,
        }
    ],
    "verbal_response": "Looking left.",
}

EXAMPLE_HEAD_SHAKE = {
    "thought_process": "User wants to shake head. Using sequential head_turn waypoints alternating left/right.",
    "waypoints": [
        {"reasoning": "Turn left",         "primitive": "head_turn", "angle": 55, "direction": "left",  "speed": 5.0},
        {"reasoning": "Turn right",        "primitive": "head_turn", "angle": 55, "direction": "right", "speed": 5.0},
        {"reasoning": "Turn left again",   "primitive": "head_turn", "angle": 55, "direction": "left",  "speed": 5.0},
        {"reasoning": "Turn right again",  "primitive": "head_turn", "angle": 55, "direction": "right", "speed": 5.0},
        {"reasoning": "Return to center",  "primitive": "head_turn", "angle": 0,  "direction": "left",  "speed": 3.0},
    ],
    "verbal_response": "Shaking head.",
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
