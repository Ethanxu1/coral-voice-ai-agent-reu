"""MobileNetV3 pose classifier + hands-close gesture for the Mac sim demo.

Mirrors the Pi-side classifier in ``robot/pi/nodes/robot_server.py`` so that the
simulation demo's ``/classify`` and ``/watch-for-action`` behave identically to
the physical robot. ``torch``/``torchvision`` are imported lazily inside the
functions so importing this module stays cheap and only the optional ``robot``
(or ``smpl``) extra is required to actually run inference.
"""

from __future__ import annotations

import math
from typing import Any

_IMAGENET_MEAN = [0.485, 0.456, 0.406]
_IMAGENET_STD = [0.229, 0.224, 0.225]

# Wrists-together threshold: wrist distance / shoulder width below this counts as
# the "hands close" intro gesture (matches robot_server.CROSS_DIST_RATIO).
CROSS_DIST_RATIO = 0.8


def select_device():
    """Pick the best available torch device (CUDA > Apple MPS > CPU)."""
    import torch

    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def load_classifier(model_path: str, device) -> tuple[Any, list[str]]:
    """Load the MobileNetV3-Large checkpoint ({'classes', 'state_dict'})."""
    import torch
    import torch.nn as nn
    from torchvision import models

    checkpoint = torch.load(model_path, map_location=device)
    classes = list(checkpoint["classes"])
    model = models.mobilenet_v3_large(weights=None)
    model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, len(classes))
    model.load_state_dict(checkpoint["state_dict"])
    model.to(device).eval()
    return model, classes


def classify_frame(
    frame_bgr, model, classes: list[str], device
) -> tuple[str, dict[str, float]]:
    """Classify a BGR frame. Returns (top_class, {class: percent})."""
    import cv2
    import torch
    import torchvision.transforms as T

    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    transform = T.Compose([
        T.ToPILImage(),
        T.Resize((224, 224)),
        T.ToTensor(),
        T.Normalize(mean=_IMAGENET_MEAN, std=_IMAGENET_STD),
    ])
    tensor = transform(rgb).unsqueeze(0).to(device)

    with torch.no_grad():
        logits = model(tensor)
        probs = torch.softmax(logits, dim=1)[0].cpu().tolist()

    pct = {cls: round(100.0 * p, 2) for cls, p in zip(classes, probs)}
    top = max(pct, key=pct.get)
    return top, pct


def hands_close(norm_landmarks: list[dict]) -> bool:
    """True when both wrists are close together relative to shoulder width.

    Uses MediaPipe pose indices (11/12 shoulders, 15/16 wrists). Mirrors
    ``robot_server._hands_close`` so the sim trigger matches the robot.
    """
    if len(norm_landmarks) <= 16:
        return False
    l_sho, r_sho = norm_landmarks[11], norm_landmarks[12]
    l_wri, r_wri = norm_landmarks[15], norm_landmarks[16]

    sho_w = math.hypot(l_sho["x"] - r_sho["x"], l_sho["y"] - r_sho["y"])
    if sho_w < 0.02:
        return False
    wri_d = math.hypot(l_wri["x"] - r_wri["x"], l_wri["y"] - r_wri["y"])
    return (wri_d / sho_w) < CROSS_DIST_RATIO
