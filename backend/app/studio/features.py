"""Normalized full-body pose features, quality checks, and safe SVG rendering."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

FULL_BODY_JOINTS = (0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)
UPPER_BODY_JOINTS = (0, 11, 12, 13, 14, 15, 16)
JOINT_NAMES = {
    0: "nose",
    11: "left_shoulder",
    12: "right_shoulder",
    13: "left_elbow",
    14: "right_elbow",
    15: "left_wrist",
    16: "right_wrist",
    23: "left_hip",
    24: "right_hip",
    25: "left_knee",
    26: "right_knee",
    27: "left_ankle",
    28: "right_ankle",
}
SKELETON_EDGES = (
    (11, 12),
    (11, 13),
    (13, 15),
    (12, 14),
    (14, 16),
    (23, 24),
    (11, 23),
    (12, 24),
    (23, 25),
    (25, 27),
    (24, 26),
    (26, 28),
)
UPPER_BODY_EDGES = SKELETON_EDGES[:5]
ANGLE_TRIPLETS = {
    "left_elbow_angle": (11, 13, 15),
    "right_elbow_angle": (12, 14, 16),
    "left_knee_angle": (23, 25, 27),
    "right_knee_angle": (24, 26, 28),
}
LIMBS = {
    "left_upper_arm": (11, 13),
    "left_forearm": (13, 15),
    "right_upper_arm": (12, 14),
    "right_forearm": (14, 16),
    "left_thigh": (23, 25),
    "left_shin": (25, 27),
    "right_thigh": (24, 26),
    "right_shin": (26, 28),
}


class InvalidPose(ValueError):
    """Raised when landmarks cannot form a valid full-body descriptor."""


@dataclass(frozen=True, slots=True)
class PoseFeatures:
    names: tuple[str, ...]
    values: tuple[float, ...]
    weights: tuple[float, ...]

    def with_feature_weight(self, name: str, weight: float) -> PoseFeatures:
        if not math.isfinite(weight) or weight < 0:
            raise ValueError("Feature weight must be finite and non-negative")
        index = self.names.index(name)
        updated = list(self.weights)
        updated[index] = weight
        return replace(self, weights=tuple(updated))


@dataclass(frozen=True, slots=True)
class SampleQuality:
    accepted: bool
    message: str
    min_visibility: float
    mean_visibility: float


def extract_pose_features(
    landmarks: Sequence[Mapping[str, float]],
) -> PoseFeatures:
    checked = _checked_landmarks(landmarks)
    shoulder_mid = _midpoint(checked[11], checked[12])
    scale = _distance(checked[11], checked[12])
    if scale <= 1e-6:
        raise InvalidPose("Shoulder width is too small")

    positions = {
        index: tuple((checked[index][axis] - shoulder_mid[axis]) / scale for axis in range(3))
        for index in FULL_BODY_JOINTS
    }
    names: list[str] = []
    values: list[float] = []
    weights: list[float] = []

    for index in FULL_BODY_JOINTS:
        visibility = checked[index][3]
        feature_weight = visibility if index in UPPER_BODY_JOINTS else 0.0
        for axis, value in zip(("x", "y", "z"), positions[index], strict=True):
            names.append(f"{JOINT_NAMES[index]}_{axis}")
            values.append(value)
            weights.append(feature_weight)

    for name, (start, middle, end) in ANGLE_TRIPLETS.items():
        names.append(name)
        values.append(_angle(positions[start], positions[middle], positions[end]))
        weights.append(
            min(checked[start][3], checked[middle][3], checked[end][3])
            if {start, middle, end}.issubset(UPPER_BODY_JOINTS)
            else 0.0
        )

    for name, (start, end) in LIMBS.items():
        direction = _unit_direction(positions[start], positions[end])
        visibility = (
            min(checked[start][3], checked[end][3])
            if {start, end}.issubset(UPPER_BODY_JOINTS)
            else 0.0
        )
        for axis, value in zip(("x", "y", "z"), direction, strict=True):
            names.append(f"{name}_{axis}")
            values.append(value)
            weights.append(visibility)

    return PoseFeatures(tuple(names), tuple(values), tuple(weights))


def validate_training_sample(
    landmarks: Sequence[Mapping[str, float]], visibility_threshold: float = 0.5
) -> SampleQuality:
    try:
        checked = _checked_landmarks(landmarks)
        extract_pose_features(landmarks)
    except InvalidPose as exc:
        return SampleQuality(False, str(exc), 0.0, 0.0)

    visibilities = [checked[index][3] for index in UPPER_BODY_JOINTS]
    minimum = min(visibilities)
    mean = sum(visibilities) / len(visibilities)
    if minimum < visibility_threshold:
        return SampleQuality(False, "Upper body not visible", minimum, mean)
    return SampleQuality(True, "Sample ready", minimum, mean)


def render_skeleton_svg(
    landmarks: Sequence[Mapping[str, float]], width: int = 180, height: int = 220
) -> str:
    checked = _checked_landmarks(landmarks)
    xs = [checked[index][0] for index in UPPER_BODY_JOINTS]
    ys = [checked[index][1] for index in UPPER_BODY_JOINTS]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    x_span = max(x_max - x_min, 1e-6)
    y_span = max(y_max - y_min, 1e-6)
    padding = 12.0

    def point(index: int) -> tuple[float, float]:
        x = padding + (checked[index][0] - x_min) / x_span * (width - 2 * padding)
        y = padding + (checked[index][1] - y_min) / y_span * (height - 2 * padding)
        return x, y

    lines = []
    for start, end in UPPER_BODY_EDGES:
        x1, y1 = point(start)
        x2, y2 = point(end)
        lines.append(
            f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" '
            'y2="{y2:.2f}" stroke="currentColor" stroke-width="4" '
            'stroke-linecap="round" />'.format(y2=y2)
        )
    circles = [
        f'<circle cx="{point(index)[0]:.2f}" cy="{point(index)[1]:.2f}" '
        'r="4" fill="currentColor" />'
        for index in UPPER_BODY_JOINTS
    ]
    content = "".join(lines + circles)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" aria-hidden="true">{content}</svg>'
    )


def _checked_landmarks(
    landmarks: Sequence[Mapping[str, float]],
) -> dict[int, tuple[float, float, float, float]]:
    if len(landmarks) <= max(FULL_BODY_JOINTS):
        raise InvalidPose("Full body landmarks are required")
    checked: dict[int, tuple[float, float, float, float]] = {}
    for index in FULL_BODY_JOINTS:
        landmark = landmarks[index]
        try:
            values = (
                float(landmark["x"]),
                float(landmark["y"]),
                float(landmark.get("z", 0.0)),
                float(landmark.get("visibility", 0.0)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidPose(f"Landmark {index} is incomplete") from exc
        if not all(math.isfinite(value) for value in values):
            raise InvalidPose(f"Landmark {index} values must be finite")
        checked[index] = values
    return checked


def _midpoint(
    left: tuple[float, ...], right: tuple[float, ...]
) -> tuple[float, float, float]:
    return tuple((left[axis] + right[axis]) / 2 for axis in range(3))  # type: ignore[return-value]


def _distance(left: Sequence[float], right: Sequence[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))


def _unit_direction(start: Sequence[float], end: Sequence[float]) -> tuple[float, ...]:
    vector = tuple(b - a for a, b in zip(start, end, strict=True))
    length = math.sqrt(sum(value * value for value in vector))
    if length <= 1e-9:
        return tuple(0.0 for _ in vector)
    return tuple(value / length for value in vector)


def _angle(start: Sequence[float], middle: Sequence[float], end: Sequence[float]) -> float:
    first = tuple(a - b for a, b in zip(start, middle, strict=True))
    second = tuple(a - b for a, b in zip(end, middle, strict=True))
    denominator = math.sqrt(sum(v * v for v in first)) * math.sqrt(
        sum(v * v for v in second)
    )
    if denominator <= 1e-9:
        return 0.0
    cosine = sum(a * b for a, b in zip(first, second, strict=True)) / denominator
    return math.acos(max(-1.0, min(1.0, cosine))) / math.pi
