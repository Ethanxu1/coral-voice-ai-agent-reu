"""InsightFace ArcFace embeddings for subject re-identification.

Wraps the InsightFace `buffalo_s` pack (SCRFD detector + MobileFaceNet
recognition, ~50MB) as a small, lazy-loaded face embedder. We feed it face
crops derived from MediaPipe's named face landmarks rather than running
SCRFD on the whole frame — this avoids double-detection work and keeps the
per-subject cost bounded.

The `insightface` and `onnxruntime` packages are optional; the class only
imports them on the first `embed_from_face_bbox` call, so environments
without the `reid` extra installed can still import this module without
error (construction will fail on first use with a clear message).
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

import cv2
import numpy as np

log = logging.getLogger("vision.face_embedder")

_FACE_CROP_MARGIN = 0.30
# Top of the named-landmark bbox sits at the eyes; the forehead is not
# represented. Pad extra vertical margin at the top so SCRFD sees a full face.
_FACE_TOP_EXTRA_MARGIN = 0.35
_DEFAULT_DET_SIZE = (320, 320)


class FaceEmbedder:
    def __init__(
        self,
        det_size: tuple[int, int] = _DEFAULT_DET_SIZE,
        providers: Optional[list[str]] = None,
    ):
        self._det_size = det_size
        self._providers = providers or ["CPUExecutionProvider"]
        self._app = None
        self._init_lock = threading.Lock()
        self._init_failed = False

    def _lazy_init(self) -> bool:
        if self._app is not None:
            return True
        if self._init_failed:
            return False
        with self._init_lock:
            if self._app is not None:
                return True
            if self._init_failed:
                return False
            try:
                from insightface.app import FaceAnalysis
            except ImportError as e:
                log.warning("insightface not installed (%s); face embeddings disabled. Install with: uv sync --extra reid", e)
                self._init_failed = True
                return False
            try:
                log.info("Loading InsightFace buffalo_s (first run downloads ~50MB to ~/.insightface/models/)")
                app = FaceAnalysis(
                    name="buffalo_s",
                    allowed_modules=["detection", "recognition"],
                    providers=self._providers,
                )
                app.prepare(ctx_id=-1, det_size=self._det_size)
                self._app = app
                log.info("InsightFace ready")
                return True
            except Exception as e:  # noqa: BLE001 — surface any load failure once
                log.warning("Failed to load InsightFace (%s); face embeddings disabled", e)
                self._init_failed = True
                return False

    def warmup(self) -> None:
        """Pre-load the model so the first user gesture doesn't pay the cost."""
        self._lazy_init()

    def embed_from_face_bbox(
        self,
        frame_bgr: np.ndarray,
        face_bbox_xyxy: tuple[int, int, int, int],
    ) -> Optional[tuple[np.ndarray, float]]:
        """Return (L2-normalized 512-d embedding, det_score) for the cropped face.

        Runs SCRFD on the padded crop to validate the face is present and to
        get InsightFace's own 5-point alignment before recognition.
        """
        if not self._lazy_init():
            return None
        x1, y1, x2, y2 = face_bbox_xyxy
        crop = _expand_and_clip(frame_bgr, x1, y1, x2, y2, margin=_FACE_CROP_MARGIN)
        if crop is None or crop.size == 0:
            return None
        try:
            faces = self._app.get(crop)
        except Exception as e:  # noqa: BLE001 — protect the vision loop
            log.debug("InsightFace .get() failed on crop: %s", e)
            return None
        if not faces:
            return None
        face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        embedding = getattr(face, "normed_embedding", None)
        if embedding is None:
            return None
        det_score = float(getattr(face, "det_score", 0.0))
        return embedding.astype(np.float32), det_score


def face_bbox_from_named_landmarks(
    face_landmarks: list[dict],
    frame_width: int,
    frame_height: int,
) -> Optional[tuple[int, int, int, int]]:
    """Convert MediaPipe named face landmarks (nose_tip/chin/eyes/ears) to a pixel bbox.

    The named subset has no forehead point, so we pad the top edge extra to
    include the hairline. Returns None if the landmarks span too little of
    the frame for a meaningful face.
    """
    if not face_landmarks or frame_width <= 0 or frame_height <= 0:
        return None
    xs = [lm.get("x", 0.0) for lm in face_landmarks]
    ys = [lm.get("y", 0.0) for lm in face_landmarks]
    if not xs or not ys:
        return None
    x_min = max(0.0, min(xs))
    x_max = min(1.0, max(xs))
    y_min = max(0.0, min(ys))
    y_max = min(1.0, max(ys))
    box_w = x_max - x_min
    box_h = y_max - y_min
    if box_w < 0.02 or box_h < 0.02:
        return None
    y_min = max(0.0, y_min - _FACE_TOP_EXTRA_MARGIN * box_h)
    x1 = int(x_min * frame_width)
    x2 = int(x_max * frame_width)
    y1 = int(y_min * frame_height)
    y2 = int(y_max * frame_height)
    if x2 - x1 < 8 or y2 - y1 < 8:
        return None
    return x1, y1, x2, y2


def _expand_and_clip(
    frame_bgr: np.ndarray,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    margin: float,
) -> Optional[np.ndarray]:
    if frame_bgr is None or frame_bgr.size == 0:
        return None
    h, w = frame_bgr.shape[:2]
    box_w = x2 - x1
    box_h = y2 - y1
    if box_w <= 0 or box_h <= 0:
        return None
    pad_x = int(margin * box_w)
    pad_y = int(margin * box_h)
    x1p = max(0, x1 - pad_x)
    y1p = max(0, y1 - pad_y)
    x2p = min(w, x2 + pad_x)
    y2p = min(h, y2 + pad_y)
    if x2p - x1p < 8 or y2p - y1p < 8:
        return None
    return frame_bgr[y1p:y2p, x1p:x2p]
