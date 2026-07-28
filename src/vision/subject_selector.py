"""Subject selection and re-identification for the vision pipeline.

Selection: raise one hand above the head for 3 s to lock a subject. Re-ID:
multi-modal fusion of an ArcFace face embedding (via InsightFace) and an HSV
torso/legs appearance histogram. Face carries the signal when it is visible
and confident; the appearance histogram provides fallback when the subject
turns away or the face is briefly occluded.

The embedders are dependency-injected so tests (and installs without the
`reid` extra) can pass `None` for either or both — in that case the selector
falls back to a legacy geometry-only face embedding from MediaPipe's 468
FaceMesh landmarks.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

import numpy as np

from . import geometry
from .appearance_embedder import (
    AppearanceEmbedder,
    AppearanceEmbedding,
    average_appearance,
    ema_appearance as _ema_appearance,
)
from .face_embedder import face_bbox_from_named_landmarks

# MediaPipe face mesh landmark indices used for legacy geometric embedding.
_FACE_NOSE_TIP = 1
_FACE_LEFT_EYE = 263
_FACE_RIGHT_EYE = 33

_NOSE = geometry.NOSE
_LEFT_SHOULDER = geometry.LEFT_SHOULDER
_RIGHT_SHOULDER = geometry.RIGHT_SHOULDER
_LEFT_ELBOW = geometry.LEFT_ELBOW
_RIGHT_ELBOW = geometry.RIGHT_ELBOW
_LEFT_WRIST = geometry.LEFT_WRIST
_RIGHT_WRIST = geometry.RIGHT_WRIST

_HOLD_SECONDS = 3.0
_LOST_FRAME_THRESHOLD = int(1.5 * 30)  # ~1.5 s at 30 fps
_MAX_SUBJECTS = 4
_ANCHOR_SAMPLE_INTERVAL = 0.2
# Max centroid delta (image-normalized) between a hand-raised subject and an
# existing hold's stored centroid for the two to be treated as the same
# person. During a 3-second hold the target subject stays roughly stationary,
# so centroid tracking is far more reliable than the noisy small-ArcFace
# face similarity that used to drive hold association.
_HOLD_CENTROID_MATCH_MAX = 0.15
# Grace period before a hold is dropped when the hand-raised subject
# disappears (hand lowered or subject left frame). Buffers 1-2 frame
# pose-detection flickers without killing hold progress.
_HOLD_UNRAISE_GRACE = 0.2

# Defaults for the live-tunable thresholds. These are just seed values; the
# runtime uses whatever's on the SubjectSelector instance so the UI can update
# them mid-session without a restart. See `TUNABLE_PARAMS` for what's exposed.
_DEFAULT_FACE_MATCH_THRESHOLD = 0.40         # ArcFace cosine, typical 0.35-0.50
_DEFAULT_APPEARANCE_MATCH_THRESHOLD = 0.60   # HSV intersection, higher bar
_DEFAULT_FUSED_MATCH_THRESHOLD = 0.50        # weighted fused score
_DEFAULT_FACE_TRUST_DET_SCORE = 0.50         # min SCRFD det score
_DEFAULT_FACE_FUSION_WEIGHT = 0.75
_DEFAULT_APPEARANCE_FUSION_WEIGHT = 0.25
_DEFAULT_LEGACY_MATCH_THRESHOLD = 0.82

# Continuous anchor refresh while the subject stays selected. Prevents the
# anchor from being frozen in whatever pose was sampled during the hold.
_DEFAULT_ANCHOR_EMA_APPEARANCE = 0.05        # ~0.7 s time constant at 30 fps
_DEFAULT_ANCHOR_EMA_FACE = 0.02              # slower — face embedding is stabler
_DEFAULT_ANCHOR_UPDATE_FACE_SIM_MIN = 0.55
_DEFAULT_ANCHOR_UPDATE_DET_SCORE_MIN = 0.6

# Names of every tunable parameter, in the order the UI shows them. Each entry
# describes its display label, min/max/step, and one-line hint.
TUNABLE_PARAMS: list[dict] = [
    {"key": "fused_match_threshold", "label": "Fused threshold", "min": 0.0, "max": 1.0, "step": 0.01,
     "hint": "Lock accepts a match when weighted (face+app) score exceeds this."},
    {"key": "face_match_threshold", "label": "Face-only threshold", "min": 0.0, "max": 1.0, "step": 0.01,
     "hint": "Used when appearance is missing — pure ArcFace cosine gate."},
    {"key": "appearance_match_threshold", "label": "Appearance-only threshold", "min": 0.0, "max": 1.0, "step": 0.01,
     "hint": "Used when face is missing/untrusted — pure HSV intersection gate."},
    {"key": "face_trust_det_score", "label": "Face trust det score", "min": 0.0, "max": 1.0, "step": 0.01,
     "hint": "SCRFD detector confidence needed before face_sim is trusted."},
    {"key": "face_fusion_weight", "label": "Face fusion weight", "min": 0.0, "max": 1.0, "step": 0.05,
     "hint": "Weight on face_sim inside the fused score."},
    {"key": "appearance_fusion_weight", "label": "Appearance fusion weight", "min": 0.0, "max": 1.0, "step": 0.05,
     "hint": "Weight on app_sim inside the fused score."},
    {"key": "anchor_ema_face", "label": "Anchor EMA (face)", "min": 0.0, "max": 0.2, "step": 0.005,
     "hint": "Per-frame drift rate of the face anchor. 0 = frozen after lock."},
    {"key": "anchor_ema_appearance", "label": "Anchor EMA (appearance)", "min": 0.0, "max": 0.2, "step": 0.005,
     "hint": "Per-frame drift rate of the appearance anchor. 0 = frozen after lock."},
    {"key": "anchor_update_face_sim_min", "label": "Anchor update gate", "min": 0.0, "max": 1.0, "step": 0.01,
     "hint": "Face similarity required to drift the anchor. High = safer."},
]


class _FaceEmbedderProtocol(Protocol):
    def embed_from_face_bbox(
        self,
        frame_bgr: np.ndarray,
        face_bbox_xyxy: tuple[int, int, int, int],
    ) -> Optional[tuple[np.ndarray, float]]: ...


class _AppearanceEmbedderProtocol(Protocol):
    def embed(
        self,
        frame_bgr: np.ndarray,
        body_landmarks: list[dict],
    ) -> Optional[AppearanceEmbedding]: ...


def _lm_dist(a: dict, b: dict) -> float:
    return math.hypot(a.get("x", 0.0) - b.get("x", 0.0), a.get("y", 0.0) - b.get("y", 0.0))


def _lm_vis(lm: dict) -> float:
    return lm.get("visibility", 0.0)


def hand_raised(body_landmarks: list[dict]) -> bool:
    """True when a subject is holding the raised-hand selection gesture.

    The user raises one hand so the wrist rises above the nose. Detected from
    MediaPipe pose landmarks alone (no face model needed): for either arm, the
    wrist's image-y is above the nose's (smaller y = higher on screen), the
    wrist is above its own elbow, and wrist/elbow/shoulder/nose are all
    sufficiently visible. Torso stays unobstructed the whole time, so the
    appearance histogram anchor can be sampled directly during the hold.
    """
    if len(body_landmarks) <= max(_LEFT_WRIST, _RIGHT_WRIST):
        return False

    nose = body_landmarks[_NOSE]
    if _lm_vis(nose) < 0.5:
        return False
    nose_y = nose.get("y", 0.0)

    for wrist_i, elbow_i, shoulder_i in (
        (_LEFT_WRIST, _LEFT_ELBOW, _LEFT_SHOULDER),
        (_RIGHT_WRIST, _RIGHT_ELBOW, _RIGHT_SHOULDER),
    ):
        wrist = body_landmarks[wrist_i]
        elbow = body_landmarks[elbow_i]
        shoulder = body_landmarks[shoulder_i]
        if any(_lm_vis(lm) < 0.5 for lm in (wrist, elbow, shoulder)):
            continue
        wrist_y = wrist.get("y", 0.0)
        # y grows downward in image coords, so "above" means smaller y.
        if wrist_y < nose_y and wrist_y < elbow.get("y", 0.0):
            return True
    return False


def compute_face_embedding(face_landmarks: list[dict]) -> Optional[np.ndarray]:
    """Legacy geometric embedding from 468 MediaPipe face landmarks.

    Retained for the case where no `FaceEmbedder` is injected (tests, or
    installs without the `reid` extra). The `SubjectSelector` prefers the
    ArcFace embedding when it is available.
    """
    if len(face_landmarks) < 468:
        return None
    pts = np.array([(lm.get("x", 0.0), lm.get("y", 0.0), lm.get("z", 0.0)) for lm in face_landmarks], dtype=np.float64)
    nose = pts[_FACE_NOSE_TIP]
    left_eye = pts[_FACE_LEFT_EYE]
    right_eye = pts[_FACE_RIGHT_EYE]
    eye_dist = np.linalg.norm(left_eye - right_eye)
    if eye_dist < 1e-6:
        return None
    centered = pts - nose
    normalized = centered / eye_dist
    return normalized.flatten()


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm < 1e-9:
        return 0.0
    return float(np.dot(a, b) / norm)


def _average_embedding(embeddings: list[np.ndarray]) -> Optional[np.ndarray]:
    if not embeddings:
        return None
    mean = np.mean(np.stack(embeddings, axis=0), axis=0)
    norm = np.linalg.norm(mean)
    if norm < 1e-9:
        return None
    return mean / norm


def _subject_depth(body_landmarks: list[dict]) -> float:
    if len(body_landmarks) > max(_LEFT_SHOULDER, _RIGHT_SHOULDER):
        l_sho = body_landmarks[_LEFT_SHOULDER]
        r_sho = body_landmarks[_RIGHT_SHOULDER]
        if "zw" in l_sho and "zw" in r_sho:
            return (l_sho["zw"] + r_sho["zw"]) / 2.0
    return -_lm_dist(body_landmarks[_LEFT_SHOULDER], body_landmarks[_RIGHT_SHOULDER])


def _subject_centroid(body_landmarks: list[dict]) -> tuple[float, float]:
    indices = [geometry.LEFT_SHOULDER, geometry.RIGHT_SHOULDER, geometry.LEFT_HIP, geometry.RIGHT_HIP]
    pts = [body_landmarks[i] for i in indices if i < len(body_landmarks) and _lm_vis(body_landmarks[i]) > 0.3]
    if not pts:
        return 0.0, 0.0
    return sum(p["x"] for p in pts) / len(pts), sum(p["y"] for p in pts) / len(pts)


def _bbox_from_landmarks(body_landmarks: list[dict]) -> dict:
    xs = [lm["x"] for lm in body_landmarks if _lm_vis(lm) > 0.2]
    ys = [lm["y"] for lm in body_landmarks if _lm_vis(lm) > 0.2]
    if not xs:
        return {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    return {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}


@dataclass
class _RawSubject:
    body_landmarks: list[dict]
    face_landmarks: list[dict]
    legacy_face_embedding: Optional[np.ndarray]
    face_embedding: Optional[np.ndarray]
    face_det_score: float
    appearance: Optional[AppearanceEmbedding]
    head_pose: Optional[Any]
    depth: float
    centroid: tuple[float, float]
    bbox: dict
    hand_raised: bool


@dataclass
class _HoldState:
    started_at: float
    legacy_embedding: Optional[np.ndarray]
    face_embedding: Optional[np.ndarray]
    appearance: Optional[AppearanceEmbedding]
    centroid: tuple[float, float]
    last_seen_at: float
    legacy_buffer: list[np.ndarray] = field(default_factory=list)
    face_buffer: list[np.ndarray] = field(default_factory=list)
    appearance_buffer: list[AppearanceEmbedding] = field(default_factory=list)
    last_sample_time: float = 0.0


@dataclass
class SubjectMetrics:
    """Per-subject scoring breakdown for the tuning UI."""
    face_sim: Optional[float] = None
    app_sim: Optional[float] = None
    face_det_score: float = 0.0
    face_trusted: bool = False
    path: str = "none"  # "fused" | "face" | "appearance" | "legacy" | "none"
    score: Optional[float] = None
    passed: bool = False

    def to_dict(self) -> dict:
        return {
            "face_sim": self.face_sim,
            "app_sim": self.app_sim,
            "face_det_score": self.face_det_score,
            "face_trusted": self.face_trusted,
            "path": self.path,
            "score": self.score,
            "passed": self.passed,
        }


@dataclass
class SubjectInfo:
    id: str
    body_landmarks: list[dict]
    face_landmarks: list[dict]
    head_pose: Optional[Any]
    bbox: dict
    is_candidate: bool
    hold_progress: float
    depth: float
    metrics: Optional[SubjectMetrics] = None


@dataclass
class SelectionResult:
    state: str  # "idle" | "selecting" | "selected" | "searching"
    selected_subject_id: Optional[str]
    primary_body_landmarks: list[dict]
    primary_face_landmarks: list[dict]
    primary_head_pose: Optional[Any]
    subjects: list[SubjectInfo]


class SubjectSelector:
    """Stateful selector: selecting → selected → (searching) → selected."""

    def __init__(
        self,
        max_subjects: int = _MAX_SUBJECTS,
        face_embedder: Optional[_FaceEmbedderProtocol] = None,
        appearance_embedder: Optional[_AppearanceEmbedderProtocol] = None,
    ):
        self._max_subjects = max_subjects
        self._face_embedder = face_embedder
        self._appearance_embedder = appearance_embedder
        self._lock = threading.Lock()
        self._state = "idle"
        self._anchor_legacy: Optional[np.ndarray] = None
        self._anchor_face: Optional[np.ndarray] = None
        self._anchor_appearance: Optional[AppearanceEmbedding] = None
        self._selected_id: Optional[str] = None
        self._holds: dict[str, _HoldState] = {}
        self._lost_frames = 0
        self._hold_counter = 0
        # Live-tunable thresholds — mirror the module defaults but can be
        # rewritten mid-session via update_tuning() from the UI.
        self.face_match_threshold = _DEFAULT_FACE_MATCH_THRESHOLD
        self.appearance_match_threshold = _DEFAULT_APPEARANCE_MATCH_THRESHOLD
        self.fused_match_threshold = _DEFAULT_FUSED_MATCH_THRESHOLD
        self.face_trust_det_score = _DEFAULT_FACE_TRUST_DET_SCORE
        self.face_fusion_weight = _DEFAULT_FACE_FUSION_WEIGHT
        self.appearance_fusion_weight = _DEFAULT_APPEARANCE_FUSION_WEIGHT
        self.legacy_match_threshold = _DEFAULT_LEGACY_MATCH_THRESHOLD
        self.anchor_ema_face = _DEFAULT_ANCHOR_EMA_FACE
        self.anchor_ema_appearance = _DEFAULT_ANCHOR_EMA_APPEARANCE
        self.anchor_update_face_sim_min = _DEFAULT_ANCHOR_UPDATE_FACE_SIM_MIN
        self.anchor_update_det_score_min = _DEFAULT_ANCHOR_UPDATE_DET_SCORE_MIN

    _TUNABLE_KEYS = tuple(p["key"] for p in TUNABLE_PARAMS)

    def get_tuning(self) -> dict:
        with self._lock:
            return {k: float(getattr(self, k)) for k in self._TUNABLE_KEYS}

    def update_tuning(self, updates: dict) -> dict:
        """Apply a subset of tunable overrides. Unknown keys are ignored."""
        with self._lock:
            for k, v in updates.items():
                if k in self._TUNABLE_KEYS:
                    try:
                        setattr(self, k, float(v))
                    except (TypeError, ValueError):
                        pass
            return {k: float(getattr(self, k)) for k in self._TUNABLE_KEYS}

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def start(self) -> None:
        with self._lock:
            self._state = "selecting"
            self._clear_anchor()

    def reset(self) -> None:
        with self._lock:
            self._state = "selecting"
            self._clear_anchor()

    def _clear_anchor(self) -> None:
        self._anchor_legacy = None
        self._anchor_face = None
        self._anchor_appearance = None
        self._selected_id = None
        self._holds.clear()
        self._lost_frames = 0

    def status(self) -> dict:
        with self._lock:
            return {
                "state": self._state,
                "selected_subject_id": self._selected_id,
            }

    def process_frame(
        self,
        detected_subjects: list[dict],
        now: Optional[float] = None,
        frame_bgr: Optional[np.ndarray] = None,
    ) -> SelectionResult:
        """Process one frame of detections.

        `detected_subjects` is a list of dicts with keys `body_landmarks`,
        `face_landmarks`, `head_pose`. `frame_bgr` is the un-annotated BGR
        camera frame; when provided (and embedders are configured), it is
        used to compute ArcFace + HSV-histogram embeddings for each subject.
        """
        if now is None:
            now = time.time()

        raw_subjects = self._build_raw_subjects(detected_subjects, frame_bgr)
        raw_subjects.sort(key=lambda s: s.depth)
        raw_subjects = raw_subjects[: self._max_subjects]

        with self._lock:
            if self._state == "selecting":
                self._update_holds(raw_subjects, now)
                for hold_id, hold in list(self._holds.items()):
                    progress = min(1.0, (now - hold.started_at) / _HOLD_SECONDS)
                    if progress >= 1.0 and self._selected_id is None:
                        self._commit_anchor(hold_id, hold)
                        break
            elif self._state == "selected":
                match = self._match_to_anchor(raw_subjects)
                if match is not None:
                    matched_id, matched_sub = match
                    self._selected_id = matched_id
                    self._lost_frames = 0
                    self._maybe_refresh_anchor(matched_sub)
                else:
                    self._lost_frames += 1
                    if self._lost_frames > _LOST_FRAME_THRESHOLD:
                        self._state = "searching"
            elif self._state == "searching":
                match = self._match_to_anchor(raw_subjects)
                if match is not None:
                    matched_id, matched_sub = match
                    self._state = "selected"
                    self._selected_id = matched_id
                    self._lost_frames = 0
                    self._maybe_refresh_anchor(matched_sub)

            state = self._state
            selected_id = self._selected_id
            holds_snapshot = dict(self._holds)
            # Snapshot metrics under the lock so the UI sees exactly what
            # decided this frame's match (anchors + thresholds are consistent).
            metrics_by_idx = {i: self._compute_metrics(s) for i, s in enumerate(raw_subjects)}

        subjects_info: list[SubjectInfo] = []
        mapping = self._associate_to_holds(raw_subjects, holds_snapshot)
        for idx, sub in enumerate(raw_subjects):
            hold_id = mapping.get(idx)
            progress = 0.0
            if state == "selecting" and hold_id and sub.hand_raised:
                hold = holds_snapshot.get(hold_id)
                if hold:
                    progress = min(1.0, (now - hold.started_at) / _HOLD_SECONDS)
            subjects_info.append(SubjectInfo(
                id=hold_id or f"sub-{idx}",
                body_landmarks=sub.body_landmarks,
                face_landmarks=sub.face_landmarks,
                head_pose=sub.head_pose,
                bbox=sub.bbox,
                is_candidate=(state == "selecting" and sub.hand_raised),
                hold_progress=progress,
                depth=sub.depth,
                metrics=metrics_by_idx.get(idx),
            ))

        primary_body: list[dict] = []
        primary_face: list[dict] = []
        primary_head: Optional[dict] = None
        if state in ("selected", "searching"):
            for info in subjects_info:
                if info.id == selected_id:
                    primary_body = info.body_landmarks
                    primary_face = info.face_landmarks
                    primary_head = info.head_pose
                    break

        return SelectionResult(
            state=state,
            selected_subject_id=selected_id,
            primary_body_landmarks=primary_body,
            primary_face_landmarks=primary_face,
            primary_head_pose=primary_head,
            subjects=subjects_info,
        )

    def _build_raw_subjects(
        self,
        detected_subjects: list[dict],
        frame_bgr: Optional[np.ndarray],
    ) -> list[_RawSubject]:
        raw: list[_RawSubject] = []
        frame_h, frame_w = (frame_bgr.shape[:2] if frame_bgr is not None and frame_bgr.size > 0 else (0, 0))

        for sub in detected_subjects:
            body = sub.get("body_landmarks", [])
            face = sub.get("face_landmarks", [])
            head = sub.get("head_pose")

            legacy_emb = compute_face_embedding(face) if face else None

            face_emb: Optional[np.ndarray] = None
            face_score = 0.0
            if self._face_embedder is not None and frame_bgr is not None and face and frame_w > 0:
                bbox = face_bbox_from_named_landmarks(face, frame_w, frame_h)
                if bbox is not None:
                    result = self._face_embedder.embed_from_face_bbox(frame_bgr, bbox)
                    if result is not None:
                        face_emb, face_score = result

            appearance: Optional[AppearanceEmbedding] = None
            if self._appearance_embedder is not None and frame_bgr is not None and body:
                appearance = self._appearance_embedder.embed(frame_bgr, body)

            raw.append(_RawSubject(
                body_landmarks=body,
                face_landmarks=face,
                legacy_face_embedding=legacy_emb,
                face_embedding=face_emb,
                face_det_score=face_score,
                appearance=appearance,
                head_pose=head,
                depth=_subject_depth(body),
                centroid=_subject_centroid(body),
                bbox=_bbox_from_landmarks(body),
                hand_raised=hand_raised(body),
            ))
        return raw

    def _commit_anchor(self, hold_id: str, hold: _HoldState) -> None:
        """Called under lock. Promotes a completed hold into the anchor."""
        self._state = "selected"
        self._selected_id = hold_id
        self._anchor_face = _average_embedding(hold.face_buffer)
        self._anchor_appearance = average_appearance(hold.appearance_buffer)
        self._anchor_legacy = _average_embedding(hold.legacy_buffer)
        self._lost_frames = 0

    def _compute_metrics(self, sub: _RawSubject) -> SubjectMetrics:
        """Compute the per-subject scoring breakdown against the current anchor."""
        m = SubjectMetrics(face_det_score=sub.face_det_score)
        if self._anchor_face is not None and sub.face_embedding is not None:
            m.face_sim = _cosine_similarity(self._anchor_face, sub.face_embedding)
        if self._anchor_appearance is not None and sub.appearance is not None:
            m.app_sim = AppearanceEmbedder.similarity(self._anchor_appearance, sub.appearance)
        m.face_trusted = m.face_sim is not None and sub.face_det_score >= self.face_trust_det_score

        if m.face_trusted and m.app_sim is not None:
            m.path = "fused"
            m.score = self.face_fusion_weight * m.face_sim + self.appearance_fusion_weight * m.app_sim
            m.passed = m.score > self.fused_match_threshold
        elif m.face_trusted:
            m.path = "face"
            m.score = m.face_sim
            m.passed = m.face_sim > self.face_match_threshold
        elif m.app_sim is not None:
            m.path = "appearance"
            m.score = m.app_sim
            m.passed = m.app_sim > self.appearance_match_threshold
        elif self._anchor_legacy is not None and sub.legacy_face_embedding is not None:
            m.path = "legacy"
            m.score = _cosine_similarity(self._anchor_legacy, sub.legacy_face_embedding)
            m.passed = m.score > self.legacy_match_threshold
        return m

    def _score_subject(self, sub: _RawSubject) -> Optional[float]:
        """Fused re-ID score in [0, 1]. Returns None if no signal applies."""
        m = self._compute_metrics(sub)
        return m.score if m.passed else None

    def _match_to_anchor(
        self, subjects: list[_RawSubject]
    ) -> Optional[tuple[str, _RawSubject]]:
        """Return (hold_id, matched_subject) for the best match, or None."""
        if self._anchor_face is None and self._anchor_appearance is None and self._anchor_legacy is None:
            return None
        best_id: Optional[str] = None
        best_sub: Optional[_RawSubject] = None
        best_score = -1.0
        mapping = self._associate_to_holds(subjects, self._holds)
        for idx, sub in enumerate(subjects):
            score = self._score_subject(sub)
            if score is None:
                continue
            if score > best_score:
                best_score = score
                best_id = mapping.get(idx) or f"sub-{idx}"
                best_sub = sub
        if best_id is None or best_sub is None:
            return None
        return best_id, best_sub

    def _maybe_refresh_anchor(self, sub: _RawSubject) -> None:
        """EMA-refresh the anchor toward the newly-matched subject.

        Guarded on: (a) face is present and confident, (b) face similarity is
        high enough to trust this is really the same person and not a
        lookalike drifting the anchor.
        """
        if self._anchor_face is None or sub.face_embedding is None:
            return
        if sub.face_det_score < self.anchor_update_det_score_min:
            return
        face_sim = _cosine_similarity(self._anchor_face, sub.face_embedding)
        if face_sim < self.anchor_update_face_sim_min:
            return

        blended = (1.0 - self.anchor_ema_face) * self._anchor_face + self.anchor_ema_face * sub.face_embedding
        norm = float(np.linalg.norm(blended))
        if norm > 1e-9:
            self._anchor_face = (blended / norm).astype(np.float32)

        if sub.appearance is not None:
            self._anchor_appearance = _ema_appearance(
                self._anchor_appearance, sub.appearance, self.anchor_ema_appearance,
            )

    def _associate_to_holds(
        self,
        subjects: list[_RawSubject],
        holds: dict[str, _HoldState],
    ) -> dict[int, str]:
        """Map each subject index to an existing hold id.

        First pass: prefer face-embedding similarity (ArcFace when available,
        else legacy geometric). Second pass: fall back to centroid distance
        so we still label subjects whose face is not visible.
        """
        used: set[str] = set()
        mapping: dict[int, str] = {}

        for sub_idx, sub in enumerate(subjects):
            best_id: Optional[str] = None
            best_sim = 0.0
            for hold_id, hold in holds.items():
                if hold_id in used:
                    continue
                sim_result = self._hold_face_similarity(sub, hold)
                if sim_result is None:
                    continue
                sim, threshold = sim_result
                # Association bar is intentionally strict: better to fail-over
                # to centroid distance than to merge two subjects.
                if sim > best_sim and sim > threshold:
                    best_sim = sim
                    best_id = hold_id
            if best_id is not None:
                mapping[sub_idx] = best_id
                used.add(best_id)

        for sub_idx, sub in enumerate(subjects):
            if sub_idx in mapping:
                continue
            best_id = None
            best_dist = float("inf")
            for hold_id, hold in holds.items():
                if hold_id in used:
                    continue
                dist = math.hypot(sub.centroid[0] - hold.centroid[0], sub.centroid[1] - hold.centroid[1])
                if dist < best_dist and dist < 0.15:
                    best_dist = dist
                    best_id = hold_id
            if best_id is not None:
                mapping[sub_idx] = best_id
                used.add(best_id)
        return mapping

    @staticmethod
    def _hold_face_similarity(sub: _RawSubject, hold: _HoldState) -> Optional[tuple[float, float]]:
        """Return (similarity, threshold) for the best face signal available."""
        if hold.face_embedding is not None and sub.face_embedding is not None:
            return _cosine_similarity(hold.face_embedding, sub.face_embedding), 0.55
        if hold.legacy_embedding is not None and sub.legacy_face_embedding is not None:
            return _cosine_similarity(hold.legacy_embedding, sub.legacy_face_embedding), 0.85
        return None

    def _update_holds(self, subjects: list[_RawSubject], now: float) -> None:
        """Update per-subject hand-raised hold timers. Called under lock.

        Association is centroid-only during the hold. Face similarity is
        deliberately skipped here because small ArcFace packs (buffalo_s /
        MobileFaceNet) can false-positive above 0.55 cosine between two
        people at similar angles — silently swapping a hold's identity
        mid-buffer and producing a chimeric anchor at commit time. The
        centroid of a hand-raising subject barely moves over 3 s, so
        centroid tracking is both simpler and much more reliable here.

        Ambiguity rule: if two or more subjects have their hand raised in
        the same frame, we can't tell which one is the target — clear all
        holds and force a restart. This prevents a bystander's simultaneous
        raise from contaminating the buffer of the actual target.
        """
        raised_indices = [i for i, s in enumerate(subjects) if s.hand_raised]

        if len(raised_indices) > 1:
            self._holds.clear()
            return

        seen: set[str] = set()

        if raised_indices:
            sub = subjects[raised_indices[0]]
            nearest_id: Optional[str] = None
            nearest_dist = float("inf")
            for hold_id, hold in self._holds.items():
                dist = math.hypot(
                    sub.centroid[0] - hold.centroid[0],
                    sub.centroid[1] - hold.centroid[1],
                )
                if dist < nearest_dist:
                    nearest_dist = dist
                    nearest_id = hold_id

            if nearest_id is not None and nearest_dist < _HOLD_CENTROID_MATCH_MAX:
                self._touch_hold(self._holds[nearest_id], sub, now)
                seen.add(nearest_id)
            else:
                self._hold_counter += 1
                new_id = f"hold-{self._hold_counter}"
                self._holds[new_id] = self._new_hold(sub, now)
                seen.add(new_id)

        stale = [
            hid for hid, h in self._holds.items()
            if hid not in seen and now - h.last_seen_at > _HOLD_UNRAISE_GRACE
        ]
        for hid in stale:
            del self._holds[hid]

    def _new_hold(self, sub: _RawSubject, now: float) -> _HoldState:
        hold = _HoldState(
            started_at=now,
            legacy_embedding=sub.legacy_face_embedding,
            face_embedding=sub.face_embedding,
            appearance=sub.appearance,
            centroid=sub.centroid,
            last_seen_at=now,
            last_sample_time=now,
        )
        if sub.face_embedding is not None:
            hold.face_buffer.append(sub.face_embedding)
        if sub.legacy_face_embedding is not None:
            hold.legacy_buffer.append(sub.legacy_face_embedding)
        if sub.appearance is not None:
            hold.appearance_buffer.append(sub.appearance)
        return hold

    def _touch_hold(self, hold: _HoldState, sub: _RawSubject, now: float) -> None:
        hold.last_seen_at = now
        hold.centroid = sub.centroid
        if sub.face_embedding is not None:
            hold.face_embedding = sub.face_embedding
        if sub.legacy_face_embedding is not None:
            hold.legacy_embedding = sub.legacy_face_embedding
        if sub.appearance is not None:
            hold.appearance = sub.appearance
        if now - hold.last_sample_time >= _ANCHOR_SAMPLE_INTERVAL:
            if sub.face_embedding is not None:
                hold.face_buffer.append(sub.face_embedding)
            if sub.legacy_face_embedding is not None:
                hold.legacy_buffer.append(sub.legacy_face_embedding)
            if sub.appearance is not None:
                hold.appearance_buffer.append(sub.appearance)
            hold.last_sample_time = now
