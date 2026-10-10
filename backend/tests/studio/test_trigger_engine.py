"""Deterministic multi-person hold and trigger state-machine tests."""

from __future__ import annotations

import pytest

from app.studio.recognizer import RecognitionResult
from app.studio.trigger_engine import TriggerEngine


def seen(subject_id: str, label: str, confidence: float) -> RecognitionResult:
    return RecognitionResult(subject_id, label, confidence, 0.2, "recognized")


@pytest.fixture
def engine() -> TriggerEngine:
    return TriggerEngine(hold_seconds=0.7, cooldown_seconds=2.0)


def _fire(
    engine: TriggerEngine, subject_id: str, label: str, start: float = 0.0
):
    engine.update([seen(subject_id, label, 0.9)], now=start)
    return engine.update([seen(subject_id, label, 0.9)], now=start + 0.7)


def test_pose_must_hold_continuously_for_point_seven_seconds(engine) -> None:
    assert engine.update([seen("p1", "hands-up", 0.9)], now=0.0) is None
    assert engine.update([seen("p1", "hands-up", 0.9)], now=0.69) is None

    decision = engine.update([seen("p1", "hands-up", 0.9)], now=0.70)

    assert decision is not None
    assert decision.subject_id == "p1"


def test_interruption_resets_hold_progress(engine) -> None:
    engine.update([seen("p1", "pose", 0.9)], now=0.0)
    engine.update([], now=0.5)

    assert engine.update([seen("p1", "pose", 0.9)], now=0.6) is None
    assert engine.update([seen("p1", "pose", 0.9)], now=1.29) is None
    assert engine.update([seen("p1", "pose", 0.9)], now=1.3) is not None


def test_equal_confidence_is_deterministic(engine) -> None:
    engine.update([seen("b", "pose", 0.9), seen("a", "pose", 0.9)], now=0.0)

    decision = engine.update(
        [seen("b", "pose", 0.9), seen("a", "pose", 0.9)], now=0.7
    )

    assert decision is not None
    assert decision.subject_id == "a"


def test_highest_confidence_person_wins(engine) -> None:
    engine.update([seen("a", "pose", 0.81), seen("b", "pose", 0.95)], now=0.0)

    decision = engine.update(
        [seen("a", "pose", 0.81), seen("b", "pose", 0.95)], now=0.7
    )

    assert decision is not None
    assert decision.subject_id == "b"


def test_busy_and_cooldown_block_other_people(engine) -> None:
    assert _fire(engine, "p1", "pose") is not None
    engine.mark_execution_started()
    engine.update([], now=0.8)  # re-arm p1 while execution remains busy
    engine.update([seen("p2", "other", 0.95)], now=1.0)
    assert engine.update([seen("p2", "other", 0.95)], now=2.0) is None

    engine.mark_execution_finished(now=2.0)
    assert engine.update([seen("p2", "other", 0.95)], now=3.9) is None
    assert engine.update([seen("p2", "other", 0.95)], now=4.0) is not None


def test_same_pose_requires_exit_before_rearm(engine) -> None:
    assert _fire(engine, "p1", "pose") is not None
    engine.mark_execution_started()
    engine.mark_execution_finished(now=1.0)

    assert engine.update([seen("p1", "pose", 0.99)], now=4.0) is None
    engine.update([], now=4.1)
    assert engine.update([seen("p1", "pose", 0.99)], now=4.2) is None
    assert engine.update([seen("p1", "pose", 0.99)], now=4.9) is not None


def test_snapshot_reports_progress_busy_and_cooldown(engine) -> None:
    engine.update([seen("p1", "pose", 0.9)], now=1.0)
    assert engine.snapshot(now=1.35).holds[0].progress == pytest.approx(0.5)

    engine.mark_execution_started()
    assert engine.snapshot(now=1.4).busy is True
    engine.mark_execution_finished(now=2.0)
    assert engine.snapshot(now=2.5).cooldown_remaining == pytest.approx(1.5)
