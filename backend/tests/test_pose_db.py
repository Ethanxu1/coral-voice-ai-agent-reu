"""Tests for the Postgres pose store (app.data.pose_db).

Needs the compose database (`docker compose up -d db`); skipped otherwise.
"""

from __future__ import annotations

import pytest

from app.data import pose_db

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def empty_db():
    pose_db.init_db()
    pose_db.clear_all_poses()
    yield
    pose_db.clear_all_poses()


def test_save_then_get_round_trips_joints():
    pose_db.save_pose("superhero", {"l_sho_pitch": 1.25, "r_sho_pitch": -0.5})
    assert pose_db.get_pose("superhero") == {"l_sho_pitch": 1.25, "r_sho_pitch": -0.5}


def test_get_is_case_insensitive():
    pose_db.save_pose("Superhero", {"head_pan": 0.1})
    assert pose_db.get_pose("SUPERHERO") == {"head_pan": 0.1}


def test_get_missing_returns_none():
    assert pose_db.get_pose("nope") is None


def test_save_overwrites_existing_name():
    pose_db.save_pose("wave", {"r_sho_pitch": 0.2})
    pose_db.save_pose("wave", {"r_sho_pitch": 0.9})
    assert pose_db.get_pose("wave") == {"r_sho_pitch": 0.9}
    assert pose_db.list_pose_names() == ["wave"]


def test_list_is_alphabetical_ignoring_case():
    for name in ["dab", "Bow", "airplane"]:
        pose_db.save_pose(name, {})
    assert pose_db.list_pose_names() == ["airplane", "Bow", "dab"]


def test_clear_removes_everything():
    pose_db.save_pose("dab", {})
    pose_db.clear_all_poses()
    assert pose_db.list_pose_names() == []
