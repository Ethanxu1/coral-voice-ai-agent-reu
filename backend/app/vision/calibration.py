from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import numpy as np


class CalibrationState(str, Enum):
    IDLE = "idle"
    COLLECTING = "collecting"
    CALIBRATED = "calibrated"


@dataclass
class CalibrationManager:
    target_frames: int = 60

    state: CalibrationState = field(default=CalibrationState.IDLE, init=False)
    frame_count: int = field(default=0, init=False)
    _yaw_acc: list = field(default_factory=list, init=False)
    _pitch_acc: list = field(default_factory=list, init=False)
    _roll_acc: list = field(default_factory=list, init=False)
    baseline_yaw: float = field(default=0.0, init=False)
    baseline_pitch: float = field(default=0.0, init=False)
    baseline_roll: float = field(default=0.0, init=False)

    @property
    def progress(self) -> float:
        if self.state == CalibrationState.CALIBRATED:
            return 1.0
        if self.state == CalibrationState.IDLE:
            return 0.0
        return min(self.frame_count / self.target_frames, 1.0)

    def start(self):
        self.state = CalibrationState.COLLECTING
        self.frame_count = 0
        self._yaw_acc.clear()
        self._pitch_acc.clear()
        self._roll_acc.clear()

    def reset(self):
        self.state = CalibrationState.IDLE
        self.frame_count = 0
        self._yaw_acc.clear()
        self._pitch_acc.clear()
        self._roll_acc.clear()
        self.baseline_yaw = 0.0
        self.baseline_pitch = 0.0
        self.baseline_roll = 0.0

    def add_frame(self, yaw: float, pitch: float, roll: float) -> bool:
        """Add a calibration frame. Returns True when calibration completes."""
        if self.state != CalibrationState.COLLECTING:
            return False
        self._yaw_acc.append(yaw)
        self._pitch_acc.append(pitch)
        self._roll_acc.append(roll)
        self.frame_count += 1
        if self.frame_count >= self.target_frames:
            self.baseline_yaw = float(np.mean(self._yaw_acc))
            self.baseline_pitch = float(np.mean(self._pitch_acc))
            self.baseline_roll = float(np.mean(self._roll_acc))
            self.state = CalibrationState.CALIBRATED
            return True
        return False

    def apply(self, yaw: float, pitch: float, roll: float) -> tuple[float, float, float]:
        """Subtract baseline offsets from raw angles."""
        return (
            yaw - self.baseline_yaw,
            pitch - self.baseline_pitch,
            roll - self.baseline_roll,
        )

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "progress": self.progress,
            "frame_count": self.frame_count,
        }
