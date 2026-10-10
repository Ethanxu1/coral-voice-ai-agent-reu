"""Lightweight visibility-weighted k-nearest-neighbor pose recognition."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
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
    ) -> None:
        if k <= 0:
            raise ValueError("k must be positive")
        if not 0 <= min_confidence <= 1:
            raise ValueError("min_confidence must be between 0 and 1")
        if not 0 <= margin <= 1:
            raise ValueError("margin must be between 0 and 1")
        self._samples = tuple(samples)
        self._k = k
        self._min_confidence = min_confidence
        self._required_margin = margin

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
        confidence = best_score / total
        runner_up = ranked[1][1] / total if len(ranked) > 1 else 0.0
        score_margin = confidence - runner_up
        if confidence < self._min_confidence:
            return RecognitionResult(
                subject_id, None, confidence, score_margin, "low_confidence"
            )
        if score_margin < self._required_margin:
            return RecognitionResult(subject_id, None, confidence, score_margin, "ambiguous")
        return RecognitionResult(
            subject_id, best_label, confidence, score_margin, "recognized"
        )


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
