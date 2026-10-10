"""Camera lifecycle contracts for the native vision service."""

from __future__ import annotations

import asyncio
import threading

from app.vision import pose_estimator, vision_server
from app.vision.pose_estimator import PoseEstimator


class _FakeCapture:
    def __init__(self) -> None:
        self.released = False

    def isOpened(self) -> bool:  # noqa: N802 - mirrors OpenCV
        return True

    def set(self, _key: int, _value: float) -> None:
        return None

    def get(self, _key: int) -> float:
        return 640.0

    def release(self) -> None:
        self.released = True


def _estimator_without_models() -> PoseEstimator:
    estimator = object.__new__(PoseEstimator)
    estimator._camera_index = 0
    estimator._target_fps = 30.0
    estimator._frame_width = 640
    estimator._frame_height = 480
    estimator._cap = None
    estimator._camera_lock = threading.Lock()
    return estimator


def test_camera_can_be_released_and_reopened(monkeypatch) -> None:
    captures: list[_FakeCapture] = []

    def open_capture(_index: int) -> _FakeCapture:
        capture = _FakeCapture()
        captures.append(capture)
        return capture

    monkeypatch.setattr(pose_estimator.cv2, "VideoCapture", open_capture)
    estimator = _estimator_without_models()

    estimator.enable_camera()
    assert estimator.camera_enabled is True

    estimator.disable_camera()
    assert estimator.camera_enabled is False
    assert captures[0].released is True

    estimator.enable_camera()
    assert estimator.camera_enabled is True
    assert len(captures) == 2


def test_disabling_camera_clears_live_subjects(monkeypatch) -> None:
    estimator = _estimator_without_models()
    estimator._cap = _FakeCapture()
    published: list[dict] = []
    broadcaster = type("Broadcaster", (), {"publish_pose": published.append})()
    monkeypatch.setattr(vision_server, "_estimator", estimator)
    monkeypatch.setattr(vision_server, "_broadcaster", broadcaster)
    monkeypatch.setattr(vision_server, "_latest_subjects", [{"id": "person-1"}])

    result = asyncio.run(vision_server.camera_off())

    assert result == {"enabled": False}
    assert vision_server._latest_subjects == []
    assert published[-1]["subjects"] == []
