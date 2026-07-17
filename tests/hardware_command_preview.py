"""Live GUI preview of the landmark -> hardware servo pipeline.

Pipeline exercised (no motors are driven — this only displays/prints what
*would* be sent):
    PoseEstimator.process_frame()   -- capture + MediaPipe landmarks + head pose
    compute_joint_targets()         -- landmarks -> joint angles (radians)
    targets_to_hardware_servo_commands()  -- radians -> physical servo pulses
                                             (per-joint stand anchor, mirror
                                             direction, damaged-servo limits)

Shows the live camera feed (with MediaPipe's own skeleton overlay). Press SPACE
to run the pipeline on the current frame and overlay the computed servo
commands on screen (also printed to console); press Q or Esc to quit.

Useful for sanity-checking the hardware conversion (see hardware_angle_utils.py)
against a real captured pose without touching the robot.

Usage:
    python tests/hardware_command_preview.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from robot.servo_config import JOINT_NAME_MAP
from vision.pose_estimator import FrameResult, PoseEstimator
from vision.pose_to_robot import (
    compute_joint_targets,
    hips_detected,
    targets_to_hardware_servo_commands,
)

DURATION_MS = 600
WINDOW = "Coral hardware command preview  [SPACE: capture   Q: quit]"
HINT_COLOR = (255, 255, 0)
RESULT_COLOR = (0, 255, 0)
ERROR_COLOR = (0, 0, 255)


def _decode(jpeg_bytes: bytes) -> np.ndarray | None:
    return cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)


def _draw_lines(frame: np.ndarray, lines: list[str], origin: tuple[int, int], color) -> None:
    x, y = origin
    for i, text in enumerate(lines):
        pos = (x, y + i * 22)
        # Black outline + colored fill so text stays legible over any background.
        cv2.putText(frame, text, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(frame, text, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1, cv2.LINE_AA)


def run_pipeline(result: FrameResult) -> tuple[list[str], bool]:
    """Run the landmark -> hardware pulse pipeline once. Returns (lines, ok)."""
    if not result.body_landmarks:
        return ["No person detected"], False

    body = result.body_landmarks
    head = result.head_pose.to_dict() if result.head_pose else None

    if not hips_detected(body):
        return ["Hips not visible — step back so your whole body is in frame"], False

    targets = compute_joint_targets(body, head)
    if not targets:
        return ["No joint targets computed (arms/head not confidently visible)"], False

    commands = targets_to_hardware_servo_commands(targets, DURATION_MS)
    lines = [f"{len(commands)} servo commands (hardware pulses):"]
    for cmd in commands:
        joint = JOINT_NAME_MAP.get(cmd.servo_id, "?")
        lines.append(f"  {joint:<12} id={cmd.servo_id:>2}  pulse={cmd.position:>4}  dur={cmd.duration_ms}ms")
    return lines, True


def main() -> None:
    estimator = PoseEstimator()
    print("Opening camera + loading MediaPipe models...")
    estimator.open()
    cv2.namedWindow(WINDOW)

    frozen_lines: list[str] = []
    frozen_ok = True
    last_result: FrameResult | None = None

    try:
        while True:
            result = estimator.process_frame()
            if result is not None:
                last_result = result
            if last_result is None:
                time.sleep(0.05)
                continue

            frame = _decode(last_result.jpeg_bytes)
            if frame is None:
                continue

            _draw_lines(frame, ["SPACE: capture + compute   Q: quit"], (12, frame.shape[0] - 12), HINT_COLOR)
            if frozen_lines:
                _draw_lines(frame, frozen_lines, (12, 26), RESULT_COLOR if frozen_ok else ERROR_COLOR)

            cv2.imshow(WINDOW, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), ord('Q'), 27):  # Q or Esc
                break
            if key == 32:  # SPACE
                frozen_lines, frozen_ok = run_pipeline(last_result)
                print("\n" + "\n".join(frozen_lines))
    finally:
        estimator.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
