"""Deterministic multi-person hold, arbitration, and cooldown state machine."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from app.studio.recognizer import RecognitionResult


@dataclass(frozen=True, slots=True)
class TriggerDecision:
    subject_id: str
    label: str
    confidence: float


@dataclass(frozen=True, slots=True)
class HoldSnapshot:
    subject_id: str
    label: str
    confidence: float
    elapsed: float
    progress: float
    armed: bool


@dataclass(frozen=True, slots=True)
class TriggerSnapshot:
    busy: bool
    cooldown_remaining: float
    holds: tuple[HoldSnapshot, ...]


@dataclass(slots=True)
class _Hold:
    subject_id: str
    label: str
    started_at: float
    confidence: float

    def elapsed(self, now: float) -> float:
        return max(0.0, now - self.started_at)

    def completed_at(self, hold_seconds: float) -> float:
        return self.started_at + hold_seconds


class TriggerEngine:
    """Tracks continuous per-person holds and emits one global winner."""

    def __init__(self, hold_seconds: float = 0.7, cooldown_seconds: float = 2.0):
        if not math.isfinite(hold_seconds) or hold_seconds <= 0:
            raise ValueError("hold_seconds must be finite and positive")
        if not math.isfinite(cooldown_seconds) or cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be finite and non-negative")
        self.hold_seconds = hold_seconds
        self.cooldown_seconds = cooldown_seconds
        self._holds: dict[str, _Hold] = {}
        self._blocked_pairs: set[tuple[str, str]] = set()
        self._busy = False
        self._cooldown_until = 0.0

    def update(
        self, results: Sequence[RecognitionResult], now: float
    ) -> TriggerDecision | None:
        """Consume one recognition frame and return the deterministic winner."""
        observations = self._best_observations(results)
        self._rearm_exited_poses(observations)
        self._update_holds(observations, now)

        if self._busy or now < self._cooldown_until:
            return None

        eligible = [
            hold
            for hold in self._holds.values()
            if hold.elapsed(now) >= self.hold_seconds
            and (hold.subject_id, hold.label) not in self._blocked_pairs
        ]
        if not eligible:
            return None

        winner = min(
            eligible,
            key=lambda hold: (
                -hold.confidence,
                hold.completed_at(self.hold_seconds),
                hold.subject_id,
                hold.label,
            ),
        )
        self._blocked_pairs.add((winner.subject_id, winner.label))
        return TriggerDecision(winner.subject_id, winner.label, winner.confidence)

    def mark_execution_started(self) -> None:
        self._busy = True

    def mark_execution_finished(
        self, now: float, cooldown_seconds: float | None = None
    ) -> None:
        self._busy = False
        cooldown = self.cooldown_seconds if cooldown_seconds is None else cooldown_seconds
        self._cooldown_until = now + max(0.0, cooldown)

    def snapshot(self, now: float) -> TriggerSnapshot:
        holds = tuple(
            HoldSnapshot(
                subject_id=hold.subject_id,
                label=hold.label,
                confidence=hold.confidence,
                elapsed=hold.elapsed(now),
                progress=min(1.0, hold.elapsed(now) / self.hold_seconds),
                armed=(hold.subject_id, hold.label) not in self._blocked_pairs,
            )
            for hold in sorted(
                self._holds.values(), key=lambda item: (item.subject_id, item.label)
            )
        )
        return TriggerSnapshot(
            busy=self._busy,
            cooldown_remaining=max(0.0, self._cooldown_until - now),
            holds=holds,
        )

    @staticmethod
    def _best_observations(
        results: Sequence[RecognitionResult],
    ) -> dict[str, RecognitionResult]:
        observations: dict[str, RecognitionResult] = {}
        for result in results:
            if result.label is None or not math.isfinite(result.confidence):
                continue
            current = observations.get(result.subject_id)
            if current is None or (-result.confidence, result.label) < (
                -current.confidence,
                current.label or "",
            ):
                observations[result.subject_id] = result
        return observations

    def _rearm_exited_poses(
        self, observations: dict[str, RecognitionResult]
    ) -> None:
        for subject_id, label in tuple(self._blocked_pairs):
            observed = observations.get(subject_id)
            if observed is None or observed.label != label:
                self._blocked_pairs.discard((subject_id, label))

    def _update_holds(
        self, observations: dict[str, RecognitionResult], now: float
    ) -> None:
        for subject_id in tuple(self._holds):
            if subject_id not in observations:
                del self._holds[subject_id]

        for subject_id, result in observations.items():
            assert result.label is not None
            hold = self._holds.get(subject_id)
            if hold is None or hold.label != result.label:
                self._holds[subject_id] = _Hold(
                    subject_id, result.label, now, result.confidence
                )
            else:
                hold.confidence = result.confidence
