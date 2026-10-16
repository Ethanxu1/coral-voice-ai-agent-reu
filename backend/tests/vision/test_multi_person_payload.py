"""Contracts for full-body multi-person vision payloads."""

from __future__ import annotations

from app.vision import geometry, vision_server
from app.vision.pose_estimator import serialize_subjects
from app.vision.subject_selector import SelectionResult, SubjectInfo


def _landmarks(x_offset: float = 0.0) -> list[dict[str, float]]:
    return [
        {
            "x": 0.25 + x_offset + index * 0.001,
            "y": 0.20 + index * 0.01,
            "z": 0.0,
            "visibility": 0.95,
            "xw": index * 0.01,
            "yw": index * 0.02,
            "zw": 0.0,
        }
        for index in range(33)
    ]


def _selection() -> SelectionResult:
    subjects = [
        SubjectInfo(
            id=f"sub-{index}",
            body_landmarks=_landmarks(index * 0.3),
            face_landmarks=[],
            head_pose=None,
            bbox={"x": index * 0.3, "y": 0.1, "width": 0.2, "height": 0.8},
            is_candidate=False,
            hold_progress=0.0,
            depth=float(index),
        )
        for index in range(2)
    ]
    return SelectionResult("idle", None, [], [], None, subjects)


def test_every_subject_payload_contains_full_landmarks() -> None:
    payload = serialize_subjects(_selection())

    assert len(payload) == 2
    assert all(len(subject["body_landmarks"]) == 33 for subject in payload)
    assert payload[0]["body_landmarks"][27]["visibility"] > 0


def test_payloads_are_independent() -> None:
    payload = serialize_subjects(_selection())

    payload[0]["body_landmarks"][0]["x"] = 99

    assert payload[1]["body_landmarks"][0]["x"] != 99


def test_studio_retarget_rejects_incomplete_legs(monkeypatch) -> None:
    body = _landmarks()
    body[geometry.LEFT_ANKLE]["visibility"] = 0.1
    monkeypatch.setattr(vision_server, "_latest_jpeg", b"jpeg")
    monkeypatch.setattr(vision_server, "_latest_landmarks", body)
    monkeypatch.setattr(vision_server, "_latest_head_pose", None)

    request = vision_server.map_features(leg_mode="retarget")
    try:
        request.send(None)
    except StopIteration as completed:
        result = completed.value
    else:  # pragma: no cover - this branch documents the no-I/O route contract
        raise AssertionError("Incomplete-leg rejection unexpectedly awaited I/O")

    assert result["pose_detected"] is False
    assert result["commands"] == []
    assert result["detail"] == "Make sure both hips, knees, and ankles are visible"


def test_studio_upper_body_mode_ignores_legs_and_uses_fixed_rate(monkeypatch) -> None:
    body = _landmarks()
    body[geometry.LEFT_HIP]["visibility"] = 0.0
    body[geometry.RIGHT_HIP]["visibility"] = 0.0
    monkeypatch.setattr(vision_server, "_latest_jpeg", b"jpeg")
    monkeypatch.setattr(vision_server, "_latest_landmarks", body)
    monkeypatch.setattr(vision_server, "_latest_head_pose", {"yaw": 10.0, "pitch": 0.0})
    monkeypatch.setattr(
        vision_server,
        "compute_joint_targets",
        lambda *_args, **_kwargs: {
            "l_sho_pitch": 0.2,
            "r_el_yaw": -0.3,
            "l_knee": 0.4,
            "head_pan": 0.1,
        },
    )

    request = vision_server.map_features(upper_body_only=True)
    try:
        request.send(None)
    except StopIteration as completed:
        result = completed.value
    else:  # pragma: no cover - upper-body mode performs no async I/O
        raise AssertionError("Upper-body mapping unexpectedly awaited I/O")

    assert result["pose_detected"] is True
    assert result["targets"] == {"l_sho_pitch": 0.2, "r_el_yaw": -0.3}
    assert {command["servo_id"] for command in result["commands"]} == {13, 20}
    assert {command["duration_ms"] for command in result["commands"]} == {400}
