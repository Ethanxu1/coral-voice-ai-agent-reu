"""Unit tests for the HSV torso/legs appearance embedder."""

from __future__ import annotations

import numpy as np
import pytest

from app.vision.appearance_embedder import AppearanceEmbedder, average_appearance


def _lm(x: float, y: float, visibility: float = 1.0) -> dict:
    return {"x": x, "y": y, "z": 0.0, "visibility": visibility}


def _pose_with_torso_and_legs() -> list[dict]:
    """33 landmarks with the torso/legs indices in a plausible upright pose."""
    p = [_lm(0.0, 0.0, visibility=0.0) for _ in range(33)]
    p[11] = _lm(0.30, 0.30)  # left shoulder
    p[12] = _lm(0.70, 0.30)  # right shoulder
    p[23] = _lm(0.35, 0.55)  # left hip
    p[24] = _lm(0.65, 0.55)  # right hip
    p[25] = _lm(0.36, 0.75)  # left knee
    p[26] = _lm(0.64, 0.75)  # right knee
    p[27] = _lm(0.36, 0.95)  # left ankle
    p[28] = _lm(0.64, 0.95)  # right ankle
    return p


def _solid_color_frame(bgr: tuple[int, int, int], size: tuple[int, int] = (480, 640)) -> np.ndarray:
    h, w = size
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    frame[:] = bgr
    return frame


def test_returns_none_when_all_landmarks_hidden() -> None:
    emb = AppearanceEmbedder()
    p = _pose_with_torso_and_legs()
    for i in range(len(p)):
        p[i]["visibility"] = 0.0
    frame = _solid_color_frame((0, 0, 255))
    assert emb.embed(frame, p) is None


def test_returns_none_on_empty_frame() -> None:
    assert AppearanceEmbedder().embed(np.zeros((0, 0, 3), dtype=np.uint8), _pose_with_torso_and_legs()) is None


def test_identical_patches_similarity_is_one() -> None:
    emb = AppearanceEmbedder()
    pose = _pose_with_torso_and_legs()
    # Use V=200 so the shadow/blowout mask (V in [30, 240]) keeps the pixels.
    red_frame = _solid_color_frame((0, 0, 200))
    a = emb.embed(red_frame, pose)
    b = emb.embed(red_frame, pose)
    assert a is not None and b is not None
    sim = AppearanceEmbedder.similarity(a, b)
    assert sim == pytest.approx(1.0, abs=1e-4)


def test_disjoint_colors_similarity_is_low() -> None:
    emb = AppearanceEmbedder()
    pose = _pose_with_torso_and_legs()
    red = emb.embed(_solid_color_frame((0, 0, 200)), pose)
    blue = emb.embed(_solid_color_frame((200, 0, 0)), pose)
    assert red is not None and blue is not None
    sim = AppearanceEmbedder.similarity(red, blue)
    assert sim < 0.05


def test_histogram_is_normalized_per_part() -> None:
    emb = AppearanceEmbedder()
    e = emb.embed(_solid_color_frame((0, 128, 0)), _pose_with_torso_and_legs())
    assert e is not None
    if e.torso_hist is not None:
        assert e.torso_hist.sum() == pytest.approx(1.0, abs=1e-4)
    if e.legs_hist is not None:
        assert e.legs_hist.sum() == pytest.approx(1.0, abs=1e-4)


def test_average_appearance_matches_single_input() -> None:
    emb = AppearanceEmbedder()
    a = emb.embed(_solid_color_frame((0, 0, 200)), _pose_with_torso_and_legs())
    assert a is not None
    avg = average_appearance([a, a, a])
    assert avg is not None
    assert AppearanceEmbedder.similarity(a, avg) == pytest.approx(1.0, abs=1e-4)
