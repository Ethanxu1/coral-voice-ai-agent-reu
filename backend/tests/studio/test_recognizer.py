"""Tests for the lightweight few-shot full-body pose recognizer."""

from __future__ import annotations

from dataclasses import replace

from app.studio.features import PoseFeatures
from app.studio.recognizer import RecognizerSample, WeightedKnnRecognizer


def _features(x: float, y: float, *, ankle_weight: float = 1.0) -> PoseFeatures:
    return PoseFeatures(
        names=("left_ankle_x", "left_wrist_y"),
        values=(x, y),
        weights=(ankle_weight, 1.0),
    )


def test_weighted_knn_rejects_ambiguous_pose() -> None:
    samples = [
        RecognizerSample("hands_up", _features(0.0, 0.0)),
        RecognizerSample("hands_up", _features(0.0, 0.1)),
        RecognizerSample("hands_up", _features(0.1, 0.0)),
        RecognizerSample("crouch", _features(1.0, 1.0)),
        RecognizerSample("crouch", _features(1.0, 0.9)),
        RecognizerSample("crouch", _features(0.9, 1.0)),
    ]
    recognizer = WeightedKnnRecognizer(
        samples, k=6, min_confidence=0.50, margin=0.08
    )

    result = recognizer.classify("person-1", _features(0.5, 0.5))

    assert result.label is None
    assert result.reason == "ambiguous"


def test_low_visibility_joint_has_less_influence() -> None:
    samples = [
        RecognizerSample("wave", _features(0.0, 0.0)),
        RecognizerSample("wave", _features(0.1, 0.0)),
        RecognizerSample("wave", _features(-0.1, 0.0)),
        RecognizerSample("squat", _features(4.0, 1.0)),
        RecognizerSample("squat", _features(4.1, 1.0)),
        RecognizerSample("squat", _features(3.9, 1.0)),
    ]
    query = replace(samples[0].features, values=(4.0, 0.0)).with_feature_weight(
        "left_ankle_x", 0.01
    )

    result = WeightedKnnRecognizer(samples, min_confidence=0.5).classify("p", query)

    assert result.label == "wave"


def test_label_order_breaks_exact_ties_deterministically() -> None:
    samples = [
        RecognizerSample("zebra", _features(0.0, 0.0)),
        RecognizerSample("alpha", _features(0.0, 0.0)),
    ]

    result = WeightedKnnRecognizer(
        samples, k=2, min_confidence=0.0, margin=0.0
    ).classify("person-2", _features(0.0, 0.0))

    assert result.label == "alpha"
