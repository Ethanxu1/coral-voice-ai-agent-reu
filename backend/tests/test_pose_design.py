"""Tests for the Pose Designer (services/pose_design.py, /pose-design/*)."""

from __future__ import annotations

import json

import mujoco
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.collision.collision_checker import CollisionChecker
from app.main import create_app
from app.robot.hardware_angle_utils import hardware_units_to_rad
from app.robot.servo_config import STAND_PULSE
from app.services import pose_design
from app.services.pose_design import CONTROLS, Change, apply_changes, merge_changes
from app.state import state

ARM_STAND = {j: p for j, p in STAND_PULSE.items() if "_sho_" in j or "_el_" in j}


def _arm_points(checker: CollisionChecker, pulses: dict[str, int], side: str):
    """World positions of the hand and shoulder for a pose (x forward, y left, z up)."""
    checker.render_pose({j: hardware_units_to_rad(p, j) for j, p in pulses.items()})
    body = lambda name: checker.data.xpos[mujoco.mj_name2id(checker.model, mujoco.mjtObj.mjOBJ_BODY, name)].copy()  # noqa: E731
    return body(f"{side}_gripper_link"), body(f"{side}_sho_pitch_link")


@pytest.mark.parametrize("name", list(CONTROLS))
def test_each_control_moves_the_arm_the_way_it_says(name):
    """The LLM is told what positive means for each control; the sim must agree."""
    checker = CollisionChecker()
    side = CONTROLS[name].joint[0]
    outward = 1 if side == "l" else -1  # the robot's left is +y
    hand0, shoulder = _arm_points(checker, ARM_STAND, side)
    hand, _ = _arm_points(checker, apply_changes(ARM_STAND, {name: -20 if "elbow" in name and side == "r" else 20}), side)
    moved = hand - hand0

    if name.endswith("arm_forward"):
        assert moved[0] > 0.01 and moved[2] > 0.01
    elif name.endswith("arm_out"):
        assert outward * moved[1] > 0.01
    elif name.endswith("elbow_bend"):
        # The right elbow servo is damaged and can't bend past the stand, so it
        # is checked straightening (negative): the hand moves away from the shoulder.
        bent = np.linalg.norm(hand - shoulder) < np.linalg.norm(hand0 - shoulder)
        assert bent == (side == "l")
    else:
        assert outward * moved[1] > 0.01


def test_changes_stay_inside_the_joint_safe_range():
    pulses = apply_changes(ARM_STAND, {"right_elbow_bend": 90, "left_arm_forward": 180})
    assert pulses["r_el_yaw"] == 850  # damaged servo: never past its stand
    assert pulses["l_sho_pitch"] == 150


def test_merge_sums_a_control_named_twice_and_drops_no_ops():
    changes = [
        Change(control="left_arm_out", degrees=10),
        Change(control="left_arm_out", degrees=5),
        Change(control="right_arm_out", degrees=0.2),
    ]
    assert merge_changes(changes) == {"left_arm_out": 15}


# ── Routes ───────────────────────────────────────────────────────────────────


class _Message:
    def __init__(self, content: str) -> None:
        self.content = content


class _Response:
    def __init__(self, content: str) -> None:
        self.choices = [type("Choice", (), {"message": _Message(content)})()]


def _llm_answers(monkeypatch, content: str, seen: list | None = None) -> None:
    def create(*args, **kwargs):
        if seen is not None:
            seen.append(kwargs["messages"])
        return _Response(content)

    monkeypatch.setattr(pose_design.openai.chat.completions, "create", create)


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        state.simulator.reset_pose()
        yield c


@pytest.mark.db
def test_a_proposal_comes_back_as_a_pose_without_moving_the_robot(client, monkeypatch):
    seen: list = []
    _llm_answers(
        monkeypatch,
        json.dumps({
            "action": "propose",
            "reply": "I'll lift my right arm up by 10 degrees.",
            "changes": [{"control": "right_arm_forward", "degrees": 10}],
        }),
        seen,
    )
    before = state.simulator.get_all_joint_states()

    data = client.post("/pose-design/turn", json={
        "text": "lift your right arm up some more",
        "pulses": ARM_STAND,
        "proposal": {"right_arm_forward": 20},
        "history": [{"role": "assistant", "content": "I'll lift my right arm up by 20 degrees."}],
    }).json()

    assert data["action"] == "propose"
    assert data["changes"] == [{"control": "right_arm_forward", "label": "Right arm forward/up", "degrees": 10}]
    assert data["proposed_pulses"]["r_sho_pitch"] == STAND_PULSE["r_sho_pitch"] + 42
    assert state.simulator.get_all_joint_states() == before
    # The LLM saw the history and the waiting proposal.
    assert seen[0][1]["content"].startswith("I'll lift")
    assert "right_arm_forward +20" in seen[0][-1]["content"]


@pytest.mark.db
def test_a_proposal_shows_only_what_the_arms_can_really_do(client, monkeypatch):
    """The right elbow can't bend past its stand (damaged servo): a proposal
    asking for it lists only the change that will happen, and one asking only
    for it is no proposal at all."""
    both = [{"control": "right_elbow_bend", "degrees": 10}, {"control": "left_elbow_bend", "degrees": 10}]
    _llm_answers(monkeypatch, json.dumps({"action": "propose", "reply": "Bending!", "changes": both}))
    data = client.post("/pose-design/turn", json={"text": "bend your elbows", "pulses": ARM_STAND}).json()
    assert [c["control"] for c in data["changes"]] == ["left_elbow_bend"]

    _llm_answers(monkeypatch, json.dumps({"action": "propose", "reply": "Bending!", "changes": both[:1]}))
    data = client.post("/pose-design/turn", json={"text": "bend your right elbow", "pulses": ARM_STAND}).json()
    assert data["action"] == "chat"
    assert data["changes"] == [] and data["proposed_pulses"] is None


@pytest.mark.db
def test_an_unusable_llm_answer_asks_again_and_changes_nothing(client, monkeypatch):
    _llm_answers(monkeypatch, '{"action": "propose", "reply": "ok", "changes": [{"control": "left_leg", "degrees": 5}]}')

    data = client.post("/pose-design/turn", json={"text": "kick", "pulses": ARM_STAND}).json()

    assert data["action"] == "chat"
    assert data["proposed_pulses"] is None


@pytest.mark.db
def test_an_unknown_control_in_the_proposal_is_rejected(client):
    res = client.post("/pose-design/turn", json={"text": "yes", "pulses": ARM_STAND, "proposal": {"nose": 5}})
    assert res.status_code == 422


@pytest.mark.db
def test_preview_poses_the_ghost_without_touching_the_live_sim(client):
    targets = state.simulator.get_all_joint_states()
    live = np.frombuffer(state.simulator.get_geom_poses(), dtype=np.float32)

    raised = client.post("/pose-design/preview", json={"pulses": {"l_sho_pitch": 300}}).json()["poses"]

    assert len(raised) == len(live)
    # The left arm is raised in the ghost: some geom moved far more than the
    # live robot settles between two frames.
    assert np.abs(np.asarray(raised) - live).max() > 0.02
    assert state.simulator.get_all_joint_states() == targets
    assert state.simulator.get_actual_joint_positions(["l_sho_pitch"])["l_sho_pitch"] == pytest.approx(
        hardware_units_to_rad(STAND_PULSE["l_sho_pitch"], "l_sho_pitch"), abs=0.1
    )


@pytest.mark.parametrize("text", [
    "Save this pose!", "save it", "save", "Save my pose now.", "freeze", "Freeze!",
    "capture this", "keep this one", "remember that pose", "lock it in", "That's it, save!",
])
def test_save_command_is_recognised(text):
    assert pose_design.is_save_command(text)


@pytest.mark.parametrize("text", [
    "", "Thank you.", "keep moving", "hello coral", "look at my arms", "I'm going to raise my arm",
    "don't save this pose", "don't save it yet", "do not freeze",
])
def test_other_speech_is_not_a_save_command(text):
    assert not pose_design.is_save_command(text)


def test_save_command_route(client):
    assert client.post("/pose-design/save-command", json={"text": "save this pose"}).json() == {"save": True}
    assert client.post("/pose-design/save-command", json={"text": "keep going"}).json() == {"save": False}
