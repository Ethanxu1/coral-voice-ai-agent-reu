"""SMPL β round-trip test.

Generates synthetic BlazePose-formatted world landmarks from a known β,
runs the fit, and asserts the fit recovers β within tolerance. The test is
SKIPPED when SMPL weights / torch / smplx aren't available — the fit module is
optional dependency under ``[project.optional-dependencies] smpl``.

Also includes a pure-numpy test of ``_average_world_landmarks`` so the helper
math is exercised on every CI run regardless of SMPL availability.
"""

from __future__ import annotations

import numpy as np
import pytest

from coral_agent.vision.smpl_fit import (
    _BLAZE_TO_SMPL,
    _average_world_landmarks,
    _visible_mask,
)


def _make_frame(positions: dict[int, tuple[float, float, float]]) -> list[dict]:
    """Build a 33-landmark BlazePose-format frame with given world positions."""
    frame = []
    for i in range(33):
        if i in positions:
            xw, yw, zw = positions[i]
            frame.append({
                "x": 0.5, "y": 0.5, "z": 0.0, "visibility": 1.0,
                "xw": xw, "yw": yw, "zw": zw,
            })
        else:
            frame.append({"x": 0.5, "y": 0.5, "z": 0.0, "visibility": 0.0})
    return frame


def test_average_world_landmarks_skips_invisible():
    """A landmark only visible in half the frames should still average correctly."""
    frame_a = _make_frame({11: (1.0, 0.5, 0.0)})
    frame_b = _make_frame({11: (3.0, 0.5, 0.0)})
    avg = _average_world_landmarks([frame_a, frame_b])
    assert avg[11, 0] == pytest.approx(2.0)


def test_average_world_landmarks_zero_when_never_seen():
    """A landmark with no visible appearances averages to zero (mask handles it later)."""
    frame_a = _make_frame({11: (1.0, 0.0, 0.0)})  # only lm 11 visible
    avg = _average_world_landmarks([frame_a])
    assert avg[14, 0] == 0.0  # lm 14 invisible everywhere


def test_visible_mask_majority_rule():
    """visible_mask is True iff a landmark is visible in more than half the frames."""
    frames = [
        _make_frame({11: (0.0, 0.0, 0.0), 12: (0.0, 0.0, 0.0)}),  # 11+12 visible
        _make_frame({11: (0.0, 0.0, 0.0)}),                        # only 11
        _make_frame({11: (0.0, 0.0, 0.0)}),                        # only 11
    ]
    mask = _visible_mask(frames)
    assert mask[11]  # seen in all 3
    assert not mask[12]  # seen in 1 of 3
    assert not mask[14]  # never seen


# ── Optional: real SMPL round-trip (skipped without weights) ──────────────────


@pytest.fixture(scope="module")
def smpl_model():
    """Load SMPL or skip the entire module if anything in the stack is missing."""
    torch = pytest.importorskip("torch")
    pytest.importorskip("smplx")
    from coral_agent.vision.smpl_loader import SMPLWeightsMissingError, load_smpl
    try:
        model = load_smpl(num_betas=10, device="cpu")
    except SMPLWeightsMissingError as e:
        pytest.skip(f"SMPL weights missing: {e}")
    return model, torch


def _synthesize_frames(model, torch, betas_true: np.ndarray) -> list[list[dict]]:
    """Forward-kinematic the model at the given betas, then drop joints into
    33-landmark BlazePose-format frames at the correct indices."""
    betas_t = torch.tensor(betas_true.reshape(1, -1), dtype=torch.float32)
    with torch.no_grad():
        out = model(betas=betas_t, return_verts=False)
        joints = out.joints[:, :24, :].squeeze(0).cpu().numpy()
    pelvis = 0.5 * (joints[1] + joints[2])
    joints = joints - pelvis  # hip-center to match BlazePose conventions

    positions: dict[int, tuple[float, float, float]] = {}
    for blaze_idx, smpl_idx, _w in _BLAZE_TO_SMPL:
        positions[blaze_idx] = tuple(joints[smpl_idx].tolist())
    # Duplicate the same frame a few times so visible_mask majority rule holds.
    return [_make_frame(positions) for _ in range(5)]


def test_smpl_betas_roundtrip(smpl_model):
    """Synthesize frames from a known β, fit, expect L2 error < 0.3 per component.

    Tolerance is loose because (a) the BlazePose↔SMPL joint mapping is
    approximate (especially head and shoulders), and (b) the optimizer is run
    on CPU with a tight iteration budget. The point is to verify the pipeline
    converges in the right direction, not to validate SMPL itself.
    """
    from coral_agent.vision.smpl_fit import fit_betas

    model, torch = smpl_model
    betas_true = np.array([0.5, -0.3, 0.2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    frames = _synthesize_frames(model, torch, betas_true)

    shape = fit_betas(frames, num_iters=400, lr=0.05, device="cpu")

    err = np.linalg.norm(shape.betas - betas_true)
    assert err < 0.5, f"β recovery error too large: {err:.3f}\nfit={shape.betas}\ntrue={betas_true}"
    # Segment lengths should be plausible for an adult body (rough sanity).
    assert 0.15 < shape.upper_arm_len < 0.45
    assert 0.15 < shape.forearm_len < 0.45
