"""State checkpointing for robot control.

Enables rollback to previous states for "undo", "go back", "try again" commands.
"""

import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from coral_agent.simulator import ApolloSimulator


@dataclass
class StateCheckpoint:
    """A saved robot state checkpoint."""

    timestamp: datetime
    joint_states: dict[str, float]
    description: str  # What action led to this state


@dataclass
class StateManager:
    """Manages state checkpoints for rollback functionality."""

    max_checkpoints: int = 10
    checkpoints: deque[StateCheckpoint] = field(default_factory=deque)

    def __post_init__(self):
        # Ensure deque has maxlen set
        self.checkpoints = deque(maxlen=self.max_checkpoints)

    def save_checkpoint(
        self, simulator: "ApolloSimulator", description: str = "manual"
    ) -> None:
        """Save the current robot state as a checkpoint.

        Args:
            simulator: The simulator to get state from
            description: Description of what action led to this state
        """
        states = simulator.get_all_joint_states()
        checkpoint = StateCheckpoint(
            timestamp=datetime.now(),
            joint_states=states.copy(),
            description=description,
        )
        self.checkpoints.append(checkpoint)
        logger.info(
            f"Saved checkpoint #{len(self.checkpoints)}: {description} "
            f"({len(states)} joints)"
        )

    def get_previous_checkpoint(self, steps_back: int = 1) -> StateCheckpoint | None:
        """Get a previous checkpoint.

        Args:
            steps_back: How many steps back to go (1 = most recent)

        Returns:
            StateCheckpoint if available, None otherwise
        """
        if steps_back < 1 or steps_back > len(self.checkpoints):
            return None
        # -1 is most recent, -2 is second most recent, etc.
        index = -steps_back
        try:
            return self.checkpoints[index]
        except IndexError:
            return None

    def pop_checkpoint(self) -> StateCheckpoint | None:
        """Remove and return the most recent checkpoint.

        Returns:
            StateCheckpoint if available, None otherwise
        """
        if len(self.checkpoints) == 0:
            return None
        return self.checkpoints.pop()

    @property
    def checkpoint_count(self) -> int:
        """Number of saved checkpoints."""
        return len(self.checkpoints)

    def clear(self) -> None:
        """Clear all checkpoints."""
        self.checkpoints.clear()
        logger.info("Cleared all state checkpoints")


# Patterns to detect rollback commands
ROLLBACK_PATTERNS = [
    # Undo patterns
    (r"\b(undo|undo that|take it back|revert)\b", "undo", 1),
    # Go back patterns
    (r"\b(go back|step back|previous|back)\b", "go_back", 1),
    (r"\b(go back|step back)\s+(\d+)\s*(steps?|times?)?\b", "go_back", None),
    # Try again / retry patterns
    (r"\b(try again|redo|do it again|retry|retry that|wrong|that was wrong|that's wrong|no,?\s*retry)\b", "try_again", 1),
    # Reset patterns
    (r"\b(reset|start over|from the beginning)\b", "reset", None),
]


@dataclass
class RollbackIntent:
    """Detected rollback intent from user message."""

    command_type: str  # undo, go_back, try_again, reset
    steps: int  # Number of steps to roll back (1 for single, -1 for reset all)
    confidence: float  # How confident we are in detection


def detect_rollback_intent(message: str) -> RollbackIntent | None:
    """Detect if a user message contains a rollback intent.

    Args:
        message: User message to analyze

    Returns:
        RollbackIntent if detected, None otherwise
    """
    message_lower = message.lower().strip()

    for pattern, cmd_type, default_steps in ROLLBACK_PATTERNS:
        match = re.search(pattern, message_lower, re.IGNORECASE)
        if match:
            # Check if there's a number in the match groups
            steps = default_steps
            if default_steps is None:
                # Look for number in match groups
                for group in match.groups():
                    if group and group.isdigit():
                        steps = int(group)
                        break
                if steps is None:
                    steps = -1 if cmd_type == "reset" else 1

            confidence = 0.9 if cmd_type in ["undo", "reset"] else 0.7

            logger.info(
                f"Detected rollback intent: {cmd_type} "
                f"(steps={steps}, confidence={confidence})"
            )
            return RollbackIntent(
                command_type=cmd_type,
                steps=steps,
                confidence=confidence,
            )

    return None


async def execute_rollback(
    simulator: "ApolloSimulator",
    state_manager: StateManager,
    intent: RollbackIntent,
    interpolation_steps: int = 30,
    step_delay: float = 0.02,
) -> dict[str, float] | None:
    """Execute a rollback to a previous state.

    Args:
        simulator: The simulator to control
        state_manager: State manager with checkpoints
        intent: The rollback intent to execute
        interpolation_steps: Number of interpolation steps for smooth motion
        step_delay: Delay between interpolation steps

    Returns:
        The target joint states if successful, None otherwise
    """
    import asyncio

    # Determine which checkpoint to use
    if intent.command_type == "reset":
        # Reset to neutral - use the oldest checkpoint or neutral pose
        target_checkpoint = state_manager.get_previous_checkpoint(
            state_manager.checkpoint_count
        )
        if target_checkpoint is None:
            # No checkpoints, reset to neutral
            from coral_agent.primitives import get_primitive

            neutral = get_primitive("neutral")
            if neutral:
                target_states = neutral.joints
            else:
                logger.warning("No checkpoints and no neutral primitive")
                return None
        else:
            target_states = target_checkpoint.joint_states
    else:
        # Get the checkpoint N steps back
        steps = max(1, intent.steps)
        target_checkpoint = state_manager.get_previous_checkpoint(steps)
        if target_checkpoint is None:
            logger.warning(
                f"Cannot roll back {steps} steps - only {state_manager.checkpoint_count} checkpoints"
            )
            return None
        target_states = target_checkpoint.joint_states

    # Get current state
    current_states = simulator.get_all_joint_states()

    # Interpolate to target
    for step in range(1, interpolation_steps + 1):
        t = step / interpolation_steps

        for joint_name, target_pos in target_states.items():
            if joint_name in current_states:
                current = current_states[joint_name]
                interpolated = current + (target_pos - current) * t
                simulator.set_joint_position(joint_name, interpolated)

        await asyncio.sleep(step_delay)

    logger.info(f"Rollback complete: {intent.command_type}")

    # Remove the checkpoint we rolled back from (for undo)
    if intent.command_type == "undo" and state_manager.checkpoint_count > 0:
        state_manager.pop_checkpoint()

    return target_states
