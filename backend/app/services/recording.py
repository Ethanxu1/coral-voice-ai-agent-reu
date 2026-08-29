"""Conversation recording utilities."""

import json
from datetime import datetime
from pathlib import Path

from loguru import logger

from app import resource_path

# Setup recordings directory
RECORDINGS_DIR = resource_path.user_data_dir() / "recordings"
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


class ConversationRecorder:
    """Records conversation interactions to a JSON file for debugging."""

    def __init__(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filepath = RECORDINGS_DIR / f"conversation_{timestamp}.json"
        self.interactions: list[dict] = []
        self.start_time = datetime.now().isoformat()
        logger.info(f"Recording conversation to: {self.filepath}")

    def log_interaction(
        self,
        user_message: str,
        assistant_response: str,
        waypoints_extracted: list[dict],
        waypoints_executed: list[dict],
        router_response: dict | None = None,
    ) -> None:
        """Log a single interaction (user message + assistant response)."""
        interaction = {
            "timestamp": datetime.now().isoformat(),
            "user": user_message,
            "assistant": assistant_response,
            "router_decision": router_response,
            "waypoints": waypoints_extracted,
            "execution": waypoints_executed,
        }
        self.interactions.append(interaction)
        self._save()

    def _save(self) -> None:
        """Save the recording to disk."""
        data = {
            "session_start": self.start_time,
            "session_end": datetime.now().isoformat(),
            "interaction_count": len(self.interactions),
            "interactions": self.interactions,
        }
        with open(self.filepath, "w") as f:
            json.dump(data, f, indent=2)
        logger.debug(f"Saved {len(self.interactions)} interactions to {self.filepath}")
