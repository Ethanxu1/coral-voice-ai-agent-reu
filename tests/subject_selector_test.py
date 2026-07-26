"""Manual harness / sanity checks for subject selection and re-ID.

Run with:
    . .venv/bin/activate && PYTHONPATH=src python tests/subject_selector_test.py
"""

import math
import sys
from pathlib import Path

# tests/vision shadows src/vision when this script is run directly, so ensure
# src is on the path first.
src_root = Path(__file__).resolve().parent.parent / "src"
src_str = str(src_root)
if src_str in sys.path:
    sys.path.remove(src_str)
sys.path.insert(0, src_str)

import time  # noqa: E402
from typing import Optional  # noqa: E402

import numpy as np  # noqa: E402

from vision.appearance_embedder import AppearanceEmbedding  # noqa: E402
from vision.subject_selector import SubjectSelector, compute_face_embedding, hand_raised  # noqa: E402


def _lm(x: float, y: float, visibility: float = 1.0) -> dict:
    return {"x": x, "y": y, "z": 0.0, "visibility": visibility}


def _standing_pose() -> list[dict]:
    p = [_lm(0.0, 0.0)] * 33
    p[0] = _lm(0.5, 0.2)   # nose
    p[11] = _lm(0.4, 0.3)  # left shoulder
    p[12] = _lm(0.6, 0.3)  # right shoulder
    p[13] = _lm(0.35, 0.5)  # left elbow
    p[14] = _lm(0.65, 0.5)  # right elbow
    p[15] = _lm(0.3, 0.7)  # left wrist
    p[16] = _lm(0.7, 0.7)  # right wrist
    p[23] = _lm(0.42, 0.7)
    p[24] = _lm(0.58, 0.7)
    return p


def _hand_raised_pose() -> list[dict]:
    p = [_lm(0.0, 0.0)] * 33
    p[0] = _lm(0.5, 0.2)   # nose
    p[11] = _lm(0.4, 0.3)  # left shoulder
    p[12] = _lm(0.6, 0.3)  # right shoulder
    p[13] = _lm(0.35, 0.15)  # left elbow above shoulder
    p[14] = _lm(0.65, 0.5)   # right elbow at side
    p[15] = _lm(0.35, 0.05)  # left wrist above nose (y < 0.2)
    p[16] = _lm(0.7, 0.7)    # right wrist at side
    p[23] = _lm(0.42, 0.7)
    p[24] = _lm(0.58, 0.7)
    return p


def _face(seed: float = 0.0) -> list[dict]:
    # Distinct but deterministic face patterns; must not be pure translations
    # because the embedding normalizes out translation.
    return [
        {
            "x": 0.5 + 0.25 * math.sin(seed * 2.1 + i / 23.0) + 0.1 * math.cos(seed + i / 7.0),
            "y": 0.5 + 0.25 * math.cos(seed * 1.7 + i / 19.0) + 0.1 * math.sin(seed * 3.0 + i / 11.0),
            "z": 0.0,
        }
        for i in range(468)
    ]


def test_hand_raised() -> None:
    assert not hand_raised(_standing_pose())
    assert hand_raised(_hand_raised_pose())
    print("test_hand_raised OK")


def test_face_embedding() -> None:
    emb = compute_face_embedding(_face())
    assert emb is not None
    assert emb.shape == (468 * 3,)
    print("test_face_embedding OK")


def _named_face_lms() -> list[dict]:
    """Six named face landmarks — the subset the multi-person pipeline emits."""
    return [
        {"x": 0.50, "y": 0.35},  # nose_tip
        {"x": 0.50, "y": 0.42},  # chin
        {"x": 0.53, "y": 0.32},  # left_eye
        {"x": 0.47, "y": 0.32},  # right_eye
        {"x": 0.55, "y": 0.33},  # left_ear
        {"x": 0.45, "y": 0.33},  # right_ear
    ]


class _StubFaceEmbedder:
    """Deterministic face embedder for tests: returns a unit vector keyed off id."""

    def __init__(self, id_to_vec: dict[str, np.ndarray], det_score: float = 0.9):
        self._id_to_vec = id_to_vec
        self._det_score = det_score
        self.active_id: Optional[str] = None

    def embed_from_face_bbox(self, frame_bgr, face_bbox_xyxy):
        if self.active_id is None:
            return None
        vec = self._id_to_vec.get(self.active_id)
        if vec is None:
            return None
        return vec.astype(np.float32), self._det_score


class _StubAppearanceEmbedder:
    """Deterministic appearance embedder for tests."""

    def __init__(self, id_to_appearance: dict[str, AppearanceEmbedding]):
        self._id_to_appearance = id_to_appearance
        self.active_id: Optional[str] = None

    def embed(self, frame_bgr, body_landmarks):
        if self.active_id is None:
            return None
        return self._id_to_appearance.get(self.active_id)


def _one_hot_hist(bin_idx: int, size: int = 512) -> np.ndarray:
    h = np.zeros(size, dtype=np.float32)
    h[bin_idx] = 1.0
    return h.reshape((8, 8, 8))


def test_multimodal_selection_and_reacquisition() -> None:
    """End-to-end: lock → out-of-view → return, using stub embedders + dummy frame."""

    vec_a = np.zeros(512, dtype=np.float32); vec_a[0] = 1.0
    vec_b = np.zeros(512, dtype=np.float32); vec_b[1] = 1.0
    face_stub = _StubFaceEmbedder({"A": vec_a, "B": vec_b}, det_score=0.9)

    app_a = AppearanceEmbedding(torso_hist=_one_hot_hist(10), legs_hist=_one_hot_hist(20))
    app_b = AppearanceEmbedding(torso_hist=_one_hot_hist(100), legs_hist=_one_hot_hist(200))
    app_stub = _StubAppearanceEmbedder({"A": app_a, "B": app_b})

    sel = SubjectSelector(face_embedder=face_stub, appearance_embedder=app_stub)
    sel.start()

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    named_face = _named_face_lms()
    subject_a = {"body_landmarks": _hand_raised_pose(), "face_landmarks": named_face, "head_pose": None}
    subject_b = {"body_landmarks": _standing_pose(), "face_landmarks": named_face, "head_pose": None}

    # The stubs are shared across subjects within a frame, so this test keeps
    # only one subject per process_frame call. That's fine for verifying the
    # state machine + fusion; the multi-subject-per-frame case is exercised
    # by real integration with InsightFace at runtime.

    # Selection hold: only subject A is in view raising a hand.
    face_stub.active_id = "A"
    app_stub.active_id = "A"
    now = time.time()
    selected = False
    for i in range(120):
        r = sel.process_frame([subject_a], now=now + i / 30, frame_bgr=frame)
        if r.state == "selected":
            print(f"test_multimodal: selected after {i} frames, id={r.selected_subject_id}")
            selected = True
            break
    assert selected, "subject A should have been selected"

    # Subject A leaves — only B visible. Set stub to B; A must NOT match B.
    face_stub.active_id = "B"
    app_stub.active_id = "B"
    for i in range(60):
        r = sel.process_frame([subject_b], now=now + 5 + i / 30, frame_bgr=frame)
    assert r.state == "searching", f"expected searching, got {r.state}"
    print("test_multimodal: searching after A left; B did not steal the lock")

    # Subject A returns. Stub returns A's vec/appearance.
    face_stub.active_id = "A"
    app_stub.active_id = "A"
    for i in range(30):
        r = sel.process_frame([subject_a], now=now + 8 + i / 30, frame_bgr=frame)
    assert r.state == "selected", f"expected selected after re-acquire, got {r.state}"
    print("test_multimodal: re-acquired A")

    # Face gone (stub returns None), appearance still present as A → stay locked.
    face_stub.active_id = None
    app_stub.active_id = "A"
    for i in range(30):
        r = sel.process_frame([subject_a], now=now + 10 + i / 30, frame_bgr=frame)
    assert r.state == "selected", f"expected selected via appearance fallback, got {r.state}"
    print("test_multimodal: appearance fallback held the lock with no face")

    print("test_multimodal_selection_and_reacquisition OK")


def test_selection_and_reacquisition() -> None:
    sel = SubjectSelector()
    sel.start()

    subject_a = {"body_landmarks": _hand_raised_pose(), "face_landmarks": _face(0.0), "head_pose": None}
    subject_b = {"body_landmarks": _standing_pose(), "face_landmarks": _face(0.5), "head_pose": None}

    now = time.time()
    selected = False
    for i in range(100):
        r = sel.process_frame([subject_a, subject_b], now=now + i / 30)
        if r.state == "selected":
            print(f"test_selection: selected after {i} frames, id={r.selected_subject_id}")
            selected = True
            break
    assert selected, "subject should have been selected"

    # Subject A leaves the frame.
    for i in range(60):
        r = sel.process_frame([subject_b], now=now + 4 + i / 30)
    assert r.state == "searching", f"expected searching, got {r.state}"
    print("test_selection: searching after subject lost")

    # Subject A returns.
    for i in range(30):
        r = sel.process_frame([subject_b, subject_a], now=now + 6 + i / 30)
    assert r.state == "selected", f"expected selected, got {r.state}"
    print("test_selection: re-acquired subject")

    print("test_selection_and_reacquisition OK")


if __name__ == "__main__":
    test_hand_raised()
    test_face_embedding()
    test_selection_and_reacquisition()
    test_multimodal_selection_and_reacquisition()
