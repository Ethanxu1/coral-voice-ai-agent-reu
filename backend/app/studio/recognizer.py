"""Lightweight visibility-weighted k-nearest-neighbor pose recognition."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from app.studio.features import PoseFeatures


@dataclass(frozen=True, slots=True)
class RecognizerSample:
    label: str
    features: PoseFeatures


@dataclass(frozen=True, slots=True)
class RecognitionResult:
    subject_id: str
    label: str | None
    confidence: float
    margin: float
    reason: str
    timestamp: float = 0.0


class PoseRecognizer(Protocol):
    def classify(
        self, subject_id: str, features: PoseFeatures
    ) -> RecognitionResult: ...


class WeightedKnnRecognizer:
    """Few-shot classifier with visibility-aware distance and rejection."""

    def __init__(
        self,
        samples: Sequence[RecognizerSample],
        k: int = 3,
        min_confidence: float = 0.78,
        margin: float = 0.08,
        distance_scale: float = 2.0,
        label_thresholds: Mapping[str, float] | None = None,
    ) -> None:
        if k <= 0:
            raise ValueError("k must be positive")
        if not 0 <= min_confidence <= 1:
            raise ValueError("min_confidence must be between 0 and 1")
        if not 0 <= margin <= 1:
            raise ValueError("margin must be between 0 and 1")
        if distance_scale <= 0:
            raise ValueError("distance_scale must be positive")
        if label_thresholds and any(
            not 0 <= threshold <= 1 for threshold in label_thresholds.values()
        ):
            raise ValueError("label thresholds must be between 0 and 1")
        self._samples = tuple(samples)
        self._k = k
        self._min_confidence = min_confidence
        self._required_margin = margin
        self._distance_scale = distance_scale
        self._label_thresholds = dict(label_thresholds or {})

    def classify(
        self, subject_id: str, features: PoseFeatures
    ) -> RecognitionResult:
        if not self._samples:
            return RecognitionResult(subject_id, None, 0.0, 0.0, "no_samples")

        neighbors = sorted(
            (
                (_weighted_distance(features, sample.features), sample.label, index, sample)
                for index, sample in enumerate(self._samples)
            ),
            key=lambda item: (item[0], item[1], item[2]),
        )[: self._k]
        votes: defaultdict[str, float] = defaultdict(float)
        for distance, label, _, sample in neighbors:
            visibility = _shared_visibility(features, sample.features)
            votes[label] += visibility / max(distance, 1e-6)

        ranked = sorted(votes.items(), key=lambda item: (-item[1], item[0]))
        total = sum(score for _, score in ranked)
        if total <= 0:
            return RecognitionResult(subject_id, None, 0.0, 0.0, "low_visibility")

        best_label, best_score = ranked[0]
        acceptance_threshold = self._label_thresholds.get(
            best_label, self._min_confidence
        )
        class_confidence = best_score / total
        runner_up = ranked[1][1] / total if len(ranked) > 1 else 0.0
        score_margin = class_confidence - runner_up
        if class_confidence < acceptance_threshold:
            return RecognitionResult(
                subject_id, None, class_confidence, score_margin, "low_confidence"
            )
        if score_margin < self._required_margin:
            return RecognitionResult(
                subject_id, None, class_confidence, score_margin, "ambiguous"
            )
        proximity = 1.0 / (1.0 + self._distance_scale * neighbors[0][0])
        confidence = class_confidence * proximity
        if confidence < acceptance_threshold:
            return RecognitionResult(
                subject_id, None, confidence, score_margin, "out_of_distribution"
            )
        return RecognitionResult(
            subject_id, best_label, confidence, score_margin, "recognized"
        )


def calibrate_label_thresholds(
    samples: Sequence[RecognizerSample],
    *,
    target_thresholds: Mapping[str, float],
    floor: float = 0.65,
    tolerance: float = 0.03,
    k: int = 3,
    margin: float = 0.08,
    distance_scale: float = 2.0,
) -> dict[str, float]:
    """Calibrate each label from leave-one-out training variation."""
    if not 0 <= floor <= 1:
        raise ValueError("calibration floor must be between 0 and 1")
    if not 0 <= tolerance <= 1:
        raise ValueError("calibration tolerance must be between 0 and 1")

    scores_by_label: defaultdict[str, list[float]] = defaultdict(list)
    impostor_scores_by_label: defaultdict[str, list[float]] = defaultdict(list)
    for index, sample in enumerate(samples):
        remaining = [*samples[:index], *samples[index + 1 :]]
        if not remaining:
            continue
        result = WeightedKnnRecognizer(
            remaining,
            k=k,
            min_confidence=0.0,
            margin=margin,
            distance_scale=distance_scale,
        ).classify("calibration", sample.features)
        if result.label == sample.label:
            scores_by_label[sample.label].append(result.confidence)
        elif result.label is not None:
            impostor_scores_by_label[result.label].append(result.confidence)

    calibrated: dict[str, float] = {}
    for label, target in target_thresholds.items():
        scores = scores_by_label.get(label, [])
        if len(scores) < 2 or impostor_scores_by_label[label]:
            calibrated[label] = target
            continue

        # A configured threshold below the normal calibration floor is an
        # intentional override and must not be raised by calibration.
        lower_bound = min(floor, target)
        calibrated[label] = max(
            lower_bound,
            min(target, min(scores) - tolerance),
        )
    return calibrated


def _weighted_distance(query: PoseFeatures, sample: PoseFeatures) -> float:
    if query.names != sample.names or len(query.values) != len(sample.values):
        raise ValueError("Pose feature schemas do not match")
    if not all(math.isfinite(value) for value in (*query.values, *sample.values)):
        raise ValueError("Pose features must be finite")
    weights = [
        min(query_weight, sample_weight)
        for query_weight, sample_weight in zip(query.weights, sample.weights, strict=True)
    ]
    total_weight = sum(weights)
    if total_weight <= 0:
        return float("inf")
    squared = sum(
        weight * (query_value - sample_value) ** 2
        for query_value, sample_value, weight in zip(
            query.values, sample.values, weights, strict=True
        )
    )
    return math.sqrt(squared / total_weight)


def _shared_visibility(query: PoseFeatures, sample: PoseFeatures) -> float:
    weights = [
        min(query_weight, sample_weight)
        for query_weight, sample_weight in zip(query.weights, sample.weights, strict=True)
    ]
    return sum(weights) / len(weights) if weights else 0.0
