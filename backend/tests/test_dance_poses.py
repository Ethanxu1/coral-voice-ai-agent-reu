"""The Dance Game's preset poses (frontend/src/dance/poses.ts) must each be
reachable: a pose whose limbs overlap the body can never be reached, so the
collision check cuts every move into it short."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.collision.collision_checker import CollisionChecker
from app.robot.hardware_angle_utils import hardware_units_to_rad

POSES_TS = Path(__file__).resolve().parents[2] / "frontend/src/dance/poses.ts"


def _dance_poses() -> dict[str, dict[str, int]]:
    source = POSES_TS.read_text()
    poses = {}
    for pose_id, body in re.findall(r"id: '([^']+)'[\s\S]*?robotPulses: \{([\s\S]*?)\}", source):
        poses[pose_id] = {joint: int(p) for joint, p in re.findall(r"(\w+): (\d+)", body)}
    return poses


@pytest.fixture(scope="module")
def checker() -> CollisionChecker:
    return CollisionChecker()


def test_poses_were_found():
    assert len(_dance_poses()) == 9


@pytest.mark.parametrize("pose_id", list(_dance_poses()))
def test_dance_pose_is_collision_free(checker, pose_id):
    stand = checker.stand_joints()
    checker.render_pose(stand)
    at_stand = checker._contact_pairs()
    pulses = _dance_poses()[pose_id]

    checker.render_pose({**stand, **{j: hardware_units_to_rad(p, j) for j, p in pulses.items()}})

    assert checker._contact_pairs() - at_stand == set()
