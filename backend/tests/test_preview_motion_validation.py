"""Simulator-only preview reports safety warnings without blocking animation."""

from __future__ import annotations

from app.services import motion


class _Simulator:
    def get_all_joint_states(self) -> dict[str, float]:
        return {"l_sho_pitch": 0.0}


def _report(*, fall: bool = False, collision: bool = False) -> dict:
    return {
        "fall_blocked": fall,
        "collision_clamped": collision,
        "safe_fraction": 0.5 if collision else (0.0 if fall else 1.0),
        "bad_pairs": ["arm<->torso"] if collision else [],
        "head_z": 0.1 if fall else 0.4,
        "threshold_z": 0.25,
    }


def test_preview_reports_collision_with_a_fall_as_simulator_warning(monkeypatch) -> None:
    monkeypatch.setattr(
        motion,
        "collision_checked_targets",
        lambda *_args, **_kwargs: ({"l_sho_pitch": 0.1}, _report(fall=True, collision=True)),
    )

    result = motion.validate_preview_motion_path(
        _Simulator(), [{"l_sho_pitch": 0.5}], "preview", samples_per_transition=1
    )

    assert result.safe is True
    assert result.reason == "collision_risk"


def test_preview_continues_after_fall_and_reports_later_collision(monkeypatch) -> None:
    reports = iter([
        _report(fall=True),
        _report(collision=True),
    ])
    monkeypatch.setattr(
        motion,
        "collision_checked_targets",
        lambda _sim, targets, _context, **_kwargs: (targets, next(reports)),
    )

    result = motion.validate_preview_motion_path(
        _Simulator(), [{"l_sho_pitch": 0.5}], "preview", samples_per_transition=2
    )

    assert result.safe is True
    assert result.reason == "collision_risk"
    assert len(result.reports) == 2
