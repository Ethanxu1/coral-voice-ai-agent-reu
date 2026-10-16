"""Upper-body-only camera preview contracts for Motion Studio."""

from __future__ import annotations

import cv2
import numpy as np

from app.vision import vision_server
from app.vision.subject_selector import SubjectSelector


def _landmarks() -> list[dict[str, float]]:
    points = [
        {"x": 0.5, "y": 0.5, "visibility": 0.0}
        for _ in range(33)
    ]
    for index, x, y in (
        (0, 0.5, 0.12),
        (11, 0.35, 0.30),
        (12, 0.65, 0.30),
        (13, 0.25, 0.48),
        (14, 0.75, 0.48),
        (15, 0.18, 0.68),
        (16, 0.82, 0.68),
        (23, 0.42, 0.78),
        (24, 0.58, 0.78),
        (25, 0.42, 0.90),
        (26, 0.58, 0.90),
    ):
        points[index] = {"x": x, "y": y, "visibility": 1.0}
    return points


def test_upper_body_preview_draws_arms_but_not_legs_or_status_text() -> None:
    frame = np.zeros((200, 200, 3), dtype=np.uint8)

    rendered = vision_server.draw_upper_body_preview(frame, _landmarks())

    assert np.count_nonzero(rendered[:145]) > 0
    assert np.count_nonzero(rendered[155:]) == 0
    assert np.count_nonzero(frame) == 0


def test_upper_body_preview_can_be_encoded_as_jpeg() -> None:
    frame = np.zeros((200, 200, 3), dtype=np.uint8)

    encoded = vision_server.encode_upper_body_preview(frame, _landmarks())
    decoded = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)

    assert decoded is not None
    assert decoded.shape == frame.shape


class _FakeEstimator:
    def __init__(self) -> None:
        self.modes: list[bool] = []
        self.subject_selector = SubjectSelector()

    def set_multi_person_mode(self, enabled: bool) -> None:
        self.modes.append(enabled)


def test_pose_capture_tracking_switches_to_single_then_passive_multi_person(monkeypatch) -> None:
    estimator = _FakeEstimator()
    monkeypatch.setattr(vision_server, "_estimator", estimator)

    def complete(request):
        try:
            request.send(None)
        except StopIteration as completed:
            return completed.value
        raise AssertionError("Tracking route unexpectedly awaited I/O")

    first = complete(vision_server.studio_tracking_start("session-a"))
    second = complete(vision_server.studio_tracking_start("session-b"))
    stale_stop = complete(vision_server.studio_tracking_stop("session-a"))

    assert stale_stop["mode"] == "single_person"
    assert estimator.modes == [False, False]

    active_stop = complete(vision_server.studio_tracking_stop("session-b"))

    assert active_stop["mode"] == "multi_person"
    assert estimator.modes == [False, False, True]
    assert estimator.subject_selector.state == "idle"


def test_studio_passive_tracking_does_not_start_subject_selection(monkeypatch) -> None:
    estimator = _FakeEstimator()
    estimator.subject_selector.start()
    monkeypatch.setattr(vision_server, "_estimator", estimator)
    monkeypatch.setattr(vision_server, "_studio_tracking_session", None)

    try:
        vision_server.studio_passive_tracking().send(None)
    except StopIteration as completed:
        result = completed.value
    else:
        raise AssertionError("Passive tracking route unexpectedly awaited I/O")

    assert result == {"mode": "multi_person", "state": "idle"}
    assert estimator.modes == [True]
    assert estimator.subject_selector.state == "idle"
