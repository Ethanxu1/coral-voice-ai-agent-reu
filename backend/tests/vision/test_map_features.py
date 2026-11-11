"""/map-features with the hips out of frame (a webcam on a desk sees only the
upper body). The Pose Designer snapshot only needs the arms, so it asks for
`hipless=true`; without it the endpoint keeps asking the user to reframe."""

from __future__ import annotations

import asyncio

import pytest

from app.vision import vision_server
from tests.vision.test_pose_to_robot import _build_body

ARM_JOINTS = {f"{s}_{j}" for s in "lr" for j in ("sho_pitch", "sho_roll", "el_yaw")}


@pytest.fixture
def upper_body_only(monkeypatch):
    body = _build_body(
        l_elbow=(+0.5, -0.5, 0.0), r_elbow=(-0.5, -0.5, 0.0),  # a T
        l_wrist=(+0.8, -0.5, 0.0), r_wrist=(-0.8, -0.5, 0.0),
        img_l_elbow=(0.85, 0.40), img_r_elbow=(0.15, 0.40),
        img_l_wrist=(0.98, 0.40), img_r_wrist=(0.02, 0.40),
    )
    for i in (23, 24, 25, 26, 27, 28):  # hips, knees, ankles below the frame
        body[i]["visibility"] = 0.01
    monkeypatch.setattr(vision_server, "_latest_landmarks", body)
    monkeypatch.setattr(vision_server, "_latest_jpeg", b"jpeg")
    monkeypatch.setattr(vision_server, "_latest_head_pose", None)


def test_hipless_snapshot_retargets_the_arms(upper_body_only):
    result = asyncio.run(vision_server.map_features(hipless=True))
    assert result["pose_detected"] is True
    assert ARM_JOINTS <= set(result["targets"])


def test_without_hipless_hidden_hips_still_ask_to_reframe(upper_body_only):
    result = asyncio.run(vision_server.map_features())
    assert result["pose_detected"] is False


def test_hipless_snapshot_without_shoulders_asks_to_reframe(upper_body_only):
    vision_server._latest_landmarks[11]["visibility"] = 0.01
    result = asyncio.run(vision_server.map_features(hipless=True))
    assert result["pose_detected"] is False
