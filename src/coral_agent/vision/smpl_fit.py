"""One-shot SMPL β (shape) fit from BlazePose world landmarks.

We don't drive servos with SMPL — Phase 1 already extracts joint rotations from
world landmarks directly. This module produces:

- 10 SMPL β coefficients fit to a stable T-pose capture, and
- per-segment lengths derived by forward-kinematicking the fitted shape.

The segment lengths are what the rest of the pipeline consumes (Phase 2.3):
per-person normalization in ``pose_to_robot`` and per-user origin for the
PnP head-pose fallback in ``pose_estimator``.

Heavy imports (``torch``, ``smplx``) are deferred until ``fit_betas`` runs so
the module can be imported even when SMPL isn't installed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import geometry

# ── BlazePose → SMPL joint correspondences ────────────────────────────────────
# SMPL joint order (24): 0 pelvis, 1 l_hip, 2 r_hip, 3 spine1, 4 l_knee,
# 5 r_knee, 6 spine2, 7 l_ankle, 8 r_ankle, 9 spine3, 10 l_foot, 11 r_foot,
# 12 neck, 13 l_collar, 14 r_collar, 15 head, 16 l_shoulder, 17 r_shoulder,
# 18 l_elbow, 19 r_elbow, 20 l_wrist, 21 r_wrist, 22 l_hand, 23 r_hand.
#
# We only fit shoulders, elbows, wrists, hips, knees, ankles, and (approximately)
# the head. That's 13 keypoints, comfortably more than the 10 β degrees of
# freedom we're solving for.
_BLAZE_TO_SMPL = (
    # (blazepose_idx, smpl_joint_idx, weight)
    (geometry.LEFT_SHOULDER,  16, 1.0),
    (geometry.RIGHT_SHOULDER, 17, 1.0),
    (geometry.LEFT_ELBOW,     18, 1.0),
    (geometry.RIGHT_ELBOW,    19, 1.0),
    (geometry.LEFT_WRIST,     20, 1.0),
    (geometry.RIGHT_WRIST,    21, 1.0),
    (geometry.LEFT_HIP,        1, 1.5),  # hips anchor scale; weight up slightly
    (geometry.RIGHT_HIP,       2, 1.5),
    (25,                       4, 1.0),  # l_knee
    (26,                       5, 1.0),  # r_knee
    (27,                       7, 1.0),  # l_ankle
    (28,                       8, 1.0),  # r_ankle
    (geometry.NOSE,           15, 0.5),  # nose ≈ head, lower weight
)


@dataclass
class UserShape:
    """Result of a one-shot SMPL fit. Consumed by the rest of the vision stack."""
    betas: np.ndarray              # shape (10,)
    upper_arm_len: float           # meters; mean of left/right shoulder→elbow
    forearm_len: float             # meters; mean of left/right elbow→wrist
    thigh_len: float               # meters; mean of left/right hip→knee
    shin_len: float                # meters; mean of left/right knee→ankle
    shoulder_span: float           # meters
    hip_span: float                # meters
    head_origin_offset: np.ndarray # shape (3,); head joint relative to mid-shoulder


def _average_world_landmarks(frames: list[list[dict]]) -> np.ndarray:
    """Return mean (33, 3) world-coord array across a buffer of stable frames.

    Frames where a landmark is below the visibility threshold contribute zero
    weight for that landmark only — partial occlusions don't poison the average.
    """
    n = 33
    sums = np.zeros((n, 3), dtype=np.float64)
    counts = np.zeros(n, dtype=np.int32)
    for frame in frames:
        for i in range(min(n, len(frame))):
            lm = frame[i]
            if "xw" not in lm:
                continue
            if lm.get("visibility", 0.0) < 0.5:
                continue
            sums[i, 0] += lm["xw"]
            sums[i, 1] += lm["yw"]
            sums[i, 2] += lm["zw"]
            counts[i] += 1
    # Avoid div-by-zero; landmarks that never appeared stay at 0 but get weight 0
    safe = np.maximum(counts, 1)
    return sums / safe[:, None]


def _visible_mask(frames: list[list[dict]]) -> np.ndarray:
    """Return a (33,) bool mask: True where at least half the frames saw the lm."""
    n = 33
    counts = np.zeros(n, dtype=np.int32)
    for frame in frames:
        for i in range(min(n, len(frame))):
            lm = frame[i]
            if "xw" in lm and lm.get("visibility", 0.0) >= 0.5:
                counts[i] += 1
    return counts > (len(frames) // 2) if frames else np.zeros(n, dtype=bool)


def fit_betas(
    frames: list[list[dict]],
    *,
    num_iters: int = 200,
    lr: float = 0.05,
    device: str | None = None,
) -> UserShape:
    """Fit 10 SMPL β coefficients to a buffer of stable T-pose world landmarks.

    Body pose and global orientation are frozen at canonical (zero rotation),
    matching the assumption that the capture is a T-pose. We only solve for
    shape. The fitted model is then forward-kinematicked to read off per-segment
    lengths used downstream.

    Raises ``SMPLWeightsMissingError`` if SMPL_NEUTRAL weights are not present.
    """
    import torch  # local import — see module docstring

    from .smpl_loader import load_smpl

    if not frames:
        raise ValueError("fit_betas: empty frames buffer")

    mean_lms = _average_world_landmarks(frames)
    visible = _visible_mask(frames)

    model = load_smpl(num_betas=10, device=device)
    dev = next(model.parameters()).device

    # Build target tensor + weight mask once.
    target_pts = []
    target_smpl_idx = []
    target_weights = []
    for blaze_idx, smpl_idx, w in _BLAZE_TO_SMPL:
        if not visible[blaze_idx]:
            continue
        target_pts.append(mean_lms[blaze_idx])
        target_smpl_idx.append(smpl_idx)
        target_weights.append(w)

    if len(target_pts) < 6:
        raise RuntimeError(
            f"fit_betas: only {len(target_pts)} usable landmark correspondences; "
            "need at least 6 (capture a full-body T-pose)."
        )

    target = torch.tensor(np.stack(target_pts), dtype=torch.float32, device=dev)
    weights = torch.tensor(target_weights, dtype=torch.float32, device=dev)
    smpl_idx_t = torch.tensor(target_smpl_idx, dtype=torch.long, device=dev)

    betas = torch.zeros(1, 10, dtype=torch.float32, device=dev, requires_grad=True)
    optim = torch.optim.Adam([betas], lr=lr)

    for _ in range(num_iters):
        optim.zero_grad()
        out = model(betas=betas, return_verts=False)
        # joints: (1, 24, 3); pelvis-center so origin matches BlazePose hip-mid
        joints = out.joints[:, :24, :].squeeze(0)
        # BlazePose world coords are approximately hip-centered per the GHUM
        # docs; pelvis-center the SMPL joints so the two frames are comparable.
        pelvis = 0.5 * (joints[1] + joints[2])
        joints_centered = joints - pelvis

        pred = joints_centered[smpl_idx_t]
        diff = pred - target
        loss = (weights[:, None] * diff.pow(2)).sum() / weights.sum()
        loss.backward()
        optim.step()

    betas_np = betas.detach().cpu().numpy().reshape(-1)

    # One more forward pass to read segment lengths off the fitted shape.
    with torch.no_grad():
        out = model(betas=betas, return_verts=False)
        joints = out.joints[:, :24, :].squeeze(0).cpu().numpy()

    def seg(a: int, b: int) -> float:
        return float(np.linalg.norm(joints[a] - joints[b]))

    upper_arm = 0.5 * (seg(16, 18) + seg(17, 19))
    forearm = 0.5 * (seg(18, 20) + seg(19, 21))
    thigh = 0.5 * (seg(1, 4) + seg(2, 5))
    shin = 0.5 * (seg(4, 7) + seg(5, 8))
    shoulder_span = seg(16, 17)
    hip_span = seg(1, 2)

    mid_sho = 0.5 * (joints[16] + joints[17])
    head_offset = joints[15] - mid_sho

    return UserShape(
        betas=betas_np,
        upper_arm_len=upper_arm,
        forearm_len=forearm,
        thigh_len=thigh,
        shin_len=shin,
        shoulder_span=shoulder_span,
        hip_span=hip_span,
        head_origin_offset=head_offset,
    )
