"""Opt-in recording of the camera's body keypoints during follow mode.

2026-10-03: in the sim the robot only ever lifted its RIGHT leg. The follow
log's 2 s summaries showed both legs reading as raised whenever either was
lifted (robot-left 0.46-0.77, robot-right 0.86-1.0), so the right always
won -- but summaries can't show why. Recording the raw keypoints lets real
lifts be replayed offline through retargeting and the controller.
"""

from __future__ import annotations

import json

from app.services.pose_recording import PoseRecorder


def test_records_one_line_per_frame_with_time_and_keypoints(tmp_path):
    rec = PoseRecorder(tmp_path)
    rec.write({"type": "pose_update", "body_landmarks": [{"x": 0.1}], "head_pose": None})
    rec.write({"type": "pose_update", "body_landmarks": [{"x": 0.2}]})
    rec.close()
    lines = [json.loads(line) for line in rec.path.read_text().splitlines()]
    assert [ln["body_landmarks"] for ln in lines] == [[{"x": 0.1}], [{"x": 0.2}]]
    assert lines[0]["t"] <= lines[1]["t"]


def test_frames_without_a_body_are_skipped(tmp_path):
    rec = PoseRecorder(tmp_path)
    rec.write({"type": "pose_update", "body_landmarks": []})
    rec.close()
    assert rec.path.read_text() == ""


def test_off_unless_asked(monkeypatch):
    from app import config
    from app.services.pose_recording import recorder_if_enabled

    monkeypatch.setattr(config, "RECORD_POSES", False)
    assert recorder_if_enabled() is None
