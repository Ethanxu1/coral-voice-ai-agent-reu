"""Tests for normalized full-body pose features and thumbnails."""

from __future__ import annotations

import math
from copy import deepcopy

import pytest

from app.studio.features import (
    InvalidPose,
    extract_pose_features,
    render_skeleton_svg,
    validate_training_sample,
)


@pytest.fixture
def full_body_pose() -> list[dict[str, float]]:
    landmarks = [
        {"x": 0.5, "y": 0.5, "z": 0.0, "visibility": 0.99}
        for _ in range(33)
    ]
    points = {
        0: (0.50, 0.10),
        11: (0.38, 0.28),
        12: (0.62, 0.28),
        13: (0.30, 0.45),
        14: (0.70, 0.45),
        15: (0.24, 0.62),
        16: (0.76, 0.62),
        23: (0.43, 0.55),
        24: (0.57, 0.55),
        25: (0.40, 0.75),
        26: (0.60, 0.75),
        27: (0.38, 0.94),
        28: (0.62, 0.94),
    }
    for index, (x, y) in points.items():
        landmarks[index].update(x=x, y=y)
    return landmarks


def _transform(
    landmarks: list[dict[str, float]], scale: float, dx: float, dy: float
) -> list[dict[str, float]]:
    moved = deepcopy(landmarks)
    for landmark in moved:
        landmark["x"] = landmark["x"] * scale + dx
        landmark["y"] = landmark["y"] * scale + dy
    return moved


def test_translation_and_scale_do_not_change_features(full_body_pose) -> None:
    moved = _transform(full_body_pose, scale=1.8, dx=0.2, dy=-0.1)

    assert extract_pose_features(moved).values == pytest.approx(
        extract_pose_features(full_body_pose).values, abs=1e-5
    )


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_landmark_is_rejected(full_body_pose, bad: float) -> None:
    full_body_pose[25]["x"] = bad

    with pytest.raises(InvalidPose, match="finite"):
        extract_pose_features(full_body_pose)


def test_missing_ankle_rejects_training_sample(full_body_pose) -> None:
    full_body_pose[27]["visibility"] = 0.1

    quality = validate_training_sample(full_body_pose)

    assert quality.accepted is False
    assert quality.message == "Full body not visible"


def test_skeleton_svg_contains_full_legs_and_only_finite_coordinates(
    full_body_pose,
) -> None:
    svg = render_skeleton_svg(full_body_pose)

    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"')
    assert svg.count("<line ") == 12
    assert "nan" not in svg.lower()
    assert "inf" not in svg.lower()
    assert all(math.isfinite(value) for value in extract_pose_features(full_body_pose).values)
