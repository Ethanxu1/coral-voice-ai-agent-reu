"""Opt-in recording of the camera's body keypoints during follow mode.

One JSON line per frame -- {"t": seconds since start, "body_landmarks": [...]}
-- under logs/pose_recordings/. Keypoints only, no images; stays on this
machine. Lets real movements be replayed offline through retargeting and
the leg-lift controller (CORAL_RECORD_POSES=true).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from app import config

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "logs" / "pose_recordings"


class PoseRecorder:
    def __init__(self, directory: Path = DEFAULT_DIR):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
        self._file = self.path.open("w")
        self._t0 = time.monotonic()

    def write(self, frame: dict) -> None:
        body = frame.get("body_landmarks")
        if not body:
            return
        self._file.write(json.dumps({"t": round(time.monotonic() - self._t0, 3),
                                     "body_landmarks": body}) + "\n")

    def close(self) -> None:
        self._file.close()


def recorder_if_enabled() -> PoseRecorder | None:
    return PoseRecorder() if config.RECORD_POSES else None
