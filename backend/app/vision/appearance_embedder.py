"""HSV color-histogram appearance embeddings for subject re-identification.

Crops torso and legs patches from the raw BGR frame using MediaPipe pose
landmarks and computes per-part HSV histograms. Used as the appearance
fallback in `SubjectSelector` when the face is not visible or not confident.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from . import geometry

_TORSO_INDICES = (geometry.LEFT_SHOULDER, geometry.RIGHT_SHOULDER, geometry.LEFT_HIP, geometry.RIGHT_HIP)
_LEGS_INDICES = (geometry.LEFT_HIP, geometry.RIGHT_HIP, geometry.LEFT_KNEE, geometry.RIGHT_KNEE, geometry.LEFT_ANKLE, geometry.RIGHT_ANKLE)

_MIN_VISIBILITY = 0.4
_MIN_PART_LANDMARKS = 3
_HIST_BINS = (8, 8, 8)
_HIST_RANGES = [0, 180, 0, 256, 0, 256]
# Mask out near-black shadows and near-white blowouts before binning so the
# resulting histogram is dominated by real garment color rather than lighting.
_HSV_MASK_LO = (0, 30, 30)
_HSV_MASK_HI = (180, 255, 240)
# Torso landmarks sit on the shoulder joints; if arms are at the person's
# sides the naive bbox includes skin-colored forearms. Shrink horizontally.
_TORSO_HORIZONTAL_SHRINK = 0.20
_TORSO_WEIGHT = 0.6
_LEGS_WEIGHT = 0.4


@dataclass
class AppearanceEmbedding:
    torso_hist: Optional[np.ndarray]
    legs_hist: Optional[np.ndarray]

    @property
    def is_empty(self) -> bool:
        return self.torso_hist is None and self.legs_hist is None


class AppearanceEmbedder:
    def embed(self, frame_bgr: np.ndarray, body_landmarks: list[dict]) -> Optional[AppearanceEmbedding]:
        if frame_bgr is None or frame_bgr.size == 0 or not body_landmarks:
            return None
        h, w = frame_bgr.shape[:2]
        torso_hist = self._part_histogram(frame_bgr, body_landmarks, _TORSO_INDICES, w, h, is_torso=True)
        legs_hist = self._part_histogram(frame_bgr, body_landmarks, _LEGS_INDICES, w, h, is_torso=False)
        if torso_hist is None and legs_hist is None:
            return None
        return AppearanceEmbedding(torso_hist=torso_hist, legs_hist=legs_hist)

    def _part_histogram(
        self,
        frame_bgr: np.ndarray,
        body_landmarks: list[dict],
        indices: tuple[int, ...],
        width: int,
        height: int,
        is_torso: bool,
    ) -> Optional[np.ndarray]:
        pts = []
        for i in indices:
            if i >= len(body_landmarks):
                continue
            lm = body_landmarks[i]
            if lm.get("visibility", 0.0) < _MIN_VISIBILITY:
                continue
            pts.append(lm)
        if len(pts) < _MIN_PART_LANDMARKS:
            return None

        xs = [lm["x"] * width for lm in pts]
        ys = [lm["y"] * height for lm in pts]
        x0 = max(0, int(min(xs)))
        x1 = min(width, int(max(xs)))
        y0 = max(0, int(min(ys)))
        y1 = min(height, int(max(ys)))

        if is_torso:
            box_w = x1 - x0
            shrink = int(_TORSO_HORIZONTAL_SHRINK * box_w)
            x0 += shrink
            x1 -= shrink

        if x1 - x0 < 8 or y1 - y0 < 8:
            return None

        patch = frame_bgr[y0:y1, x0:x1]
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, _HSV_MASK_LO, _HSV_MASK_HI)
        hist = cv2.calcHist([hsv], [0, 1, 2], mask, list(_HIST_BINS), _HIST_RANGES)
        total = float(hist.sum())
        if total < 1.0:
            return None
        return (hist / total).astype(np.float32)

    @staticmethod
    def similarity(a: AppearanceEmbedding, b: AppearanceEmbedding) -> float:
        """Weighted histogram intersection in [0, 1] over parts present in both."""
        if a is None or b is None:
            return 0.0
        scores: list[float] = []
        weights: list[float] = []
        if a.torso_hist is not None and b.torso_hist is not None:
            scores.append(float(np.minimum(a.torso_hist, b.torso_hist).sum()))
            weights.append(_TORSO_WEIGHT)
        if a.legs_hist is not None and b.legs_hist is not None:
            scores.append(float(np.minimum(a.legs_hist, b.legs_hist).sum()))
            weights.append(_LEGS_WEIGHT)
        if not scores:
            return 0.0
        return sum(s * w for s, w in zip(scores, weights)) / sum(weights)


def average_appearance(embeddings: list[AppearanceEmbedding]) -> Optional[AppearanceEmbedding]:
    """Average torso and legs histograms independently and re-L1-normalize."""
    if not embeddings:
        return None
    torso_stack = [e.torso_hist for e in embeddings if e is not None and e.torso_hist is not None]
    legs_stack = [e.legs_hist for e in embeddings if e is not None and e.legs_hist is not None]
    torso_avg = _mean_l1(torso_stack)
    legs_avg = _mean_l1(legs_stack)
    if torso_avg is None and legs_avg is None:
        return None
    return AppearanceEmbedding(torso_hist=torso_avg, legs_hist=legs_avg)


def _mean_l1(hists: list[np.ndarray]) -> Optional[np.ndarray]:
    if not hists:
        return None
    stacked = np.stack(hists, axis=0)
    mean = stacked.mean(axis=0)
    total = float(mean.sum())
    if total < 1e-9:
        return None
    return (mean / total).astype(np.float32)


def ema_appearance(
    anchor: Optional[AppearanceEmbedding],
    sample: AppearanceEmbedding,
    alpha: float,
) -> AppearanceEmbedding:
    """Return an EMA-blended appearance: `anchor * (1-alpha) + sample * alpha`.

    Bootstraps any part (torso/legs) that was missing from the anchor by
    adopting the sample outright — useful when the hold sampled only legs
    (arms obscured the torso) and the first post-hold frame reveals the
    real torso color.
    """
    if anchor is None:
        return AppearanceEmbedding(torso_hist=sample.torso_hist, legs_hist=sample.legs_hist)
    return AppearanceEmbedding(
        torso_hist=_blend_hist(anchor.torso_hist, sample.torso_hist, alpha),
        legs_hist=_blend_hist(anchor.legs_hist, sample.legs_hist, alpha),
    )


def _blend_hist(
    anchor: Optional[np.ndarray],
    sample: Optional[np.ndarray],
    alpha: float,
) -> Optional[np.ndarray]:
    if sample is None:
        return anchor
    if anchor is None:
        return sample.astype(np.float32)
    blended = (1.0 - alpha) * anchor + alpha * sample
    total = float(blended.sum())
    if total < 1e-9:
        return None
    return (blended / total).astype(np.float32)
