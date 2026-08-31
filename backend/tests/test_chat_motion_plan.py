"""Integration tests for the chat motion-planning pipeline.

These tests exercise `process_chat_message` end-to-end with a mocked LLM
response and a fake simulator, proving that schema parsing, primitive
resolution, and fallback handling all converge on real servo commands.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.robot.interface import ServoCommand
from app.schemas.motion_plan import MotionPlan
from app.services.chat import HierarchicalMemory, process_chat_message
from app.services.recording import ConversationRecorder
from app.state import state
from app.state_manager import StateManager


class _FakeSimDispatcher:
    """Captures servo commands instead of calling MuJoCo."""

    def __init__(self) -> None:
        self.commands: list[ServoCommand] = []

    def send_commands(self, commands: list[ServoCommand]) -> None:
        self.commands.extend(commands)


class _FakeSimulator:
    """Minimal stand-in for AiNexSimulator."""

    JOINT_NAMES = {
        "head_pan": "head_pan_act",
        "head_tilt": "head_tilt_act",
        "l_sho_pitch": "l_sho_pitch_act",
        "l_sho_roll": "l_sho_roll_act",
        "l_el_pitch": "l_el_pitch_act",
        "l_el_yaw": "l_el_yaw_act",
        "l_gripper": "l_gripper_act",
        "r_sho_pitch": "r_sho_pitch_act",
        "r_sho_roll": "r_sho_roll_act",
        "r_el_pitch": "r_el_pitch_act",
        "r_el_yaw": "r_el_yaw_act",
        "r_gripper": "r_gripper_act",
        "l_hip_yaw": "l_hip_yaw_act",
        "l_hip_roll": "l_hip_roll_act",
        "l_hip_pitch": "l_hip_pitch_act",
        "l_knee": "l_knee_act",
        "l_ank_pitch": "l_ank_pitch_act",
        "l_ank_roll": "l_ank_roll_act",
        "r_hip_yaw": "r_hip_yaw_act",
        "r_hip_roll": "r_hip_roll_act",
        "r_hip_pitch": "r_hip_pitch_act",
        "r_knee": "r_knee_act",
        "r_ank_pitch": "r_ank_pitch_act",
        "r_ank_roll": "r_ank_roll_act",
    }

    def __init__(self) -> None:
        self._state: dict[str, float] = {name: 0.0 for name in self.JOINT_NAMES}

    def get_all_joint_states(self) -> dict[str, float]:
        return self._state.copy()

    def set_joint_position(self, joint_name: str, position: float) -> None:
        if joint_name in self._state:
            self._state[joint_name] = position


class _FakeLangfuse:
    def update_current_span(self, *args: Any, **kwargs: Any) -> None:
        pass


class _MockCompletion:
    def __init__(self, content: str) -> None:
        self.content = content

    class Usage:
        prompt_tokens = 1
        completion_tokens = 1
        total_tokens = 2

        class PromptTokensDetails:
            cached_tokens = 0

        prompt_tokens_details = PromptTokensDetails()

    usage = Usage()


class _MockChoice:
    def __init__(self, content: str) -> None:
        self.message = _MockCompletion(content)


class _MockResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_MockChoice(content)]
        self.usage = _MockCompletion.usage


@pytest.fixture
def sim_setup(monkeypatch: pytest.MonkeyPatch):
    """Provide a fake simulator/dispatcher and patch chat dependencies."""
    sim = _FakeSimulator()
    dispatcher = _FakeSimDispatcher()

    # Save and restore global state so tests don't leak.
    old_mode = state.robot_mode
    old_sim = state.simulator
    old_sim_dispatcher = state.sim_dispatcher
    old_hw = state.hardware_dispatcher
    old_hw_in_sync = state.hardware_in_sync

    state.robot_mode = "sim"
    state.simulator = sim
    state.sim_dispatcher = dispatcher
    state.hardware_dispatcher = None
    state.hardware_in_sync = False

    monkeypatch.setattr("app.services.chat.get_client", lambda: _FakeLangfuse())

    yield sim, dispatcher

    state.robot_mode = old_mode
    state.simulator = old_sim
    state.sim_dispatcher = old_sim_dispatcher
    state.hardware_dispatcher = old_hw
    state.hardware_in_sync = old_hw_in_sync


@pytest.fixture
def chat_inputs():
    return {
        "memory": HierarchicalMemory(),
        "state_manager": StateManager(),
        "recorder": ConversationRecorder(),
        "simulator_instance": _FakeSimulator(),
        "session_id": "test-session",
    }


def _make_openai_mock(content: str):
    """Return a stand-in for openai.chat.completions.create."""

    def _create(*args, **kwargs):
        return _MockResponse(content)

    return _create


def test_structured_motion_plan_executes(
    monkeypatch: pytest.MonkeyPatch, sim_setup, chat_inputs
):
    """A valid MotionPlan JSON from the LLM drives the fake dispatcher."""
    _, dispatcher = sim_setup

    plan = MotionPlan(
        action="motion",
        verbal_response="Raising my right arm!",
        satisfied=True,
        waypoints=[
            {
                "primitives": ["right_arm_forward"],
                "angle": 45.0,
                "speed": 1.0,
            }
        ],
    )
    monkeypatch.setattr(
        "app.services.chat.openai.chat.completions.create",
        _make_openai_mock(plan.model_dump_json()),
    )

    result = asyncio.run(
        process_chat_message(
            user_message="raise your right arm 45 degrees",
            sim_only=None,
            **chat_inputs,
        )
    )

    assert result["type"] == "chat_response"
    assert result["content"] == "Raising my right arm!"
    assert result["satisfied"] is True
    assert len(dispatcher.commands) == 1
    assert dispatcher.commands[0].servo_id == 14  # r_sho_pitch


def test_invalid_llm_shape_falls_back_to_deterministic_plan(
    monkeypatch: pytest.MonkeyPatch, sim_setup, chat_inputs
):
    """When the LLM returns invalid JSON, the deterministic fallback maps
    a known child phrase to motion."""
    _, dispatcher = sim_setup

    monkeypatch.setattr(
        "app.services.chat.openai.chat.completions.create",
        _make_openai_mock('{"unexpected": "shape"}'),
    )

    result = asyncio.run(
        process_chat_message(
            user_message="turn your head left",
            sim_only=None,
            **chat_inputs,
        )
    )

    assert result["type"] == "chat_response"
    assert len(dispatcher.commands) == 1
    assert dispatcher.commands[0].servo_id == 23  # head_pan


def test_unmapped_request_returns_clarification(
    monkeypatch: pytest.MonkeyPatch, sim_setup, chat_inputs
):
    """A phrase the fallback can't map and the LLM can't shape results in a
    child-friendly clarification instead of motion."""
    _, dispatcher = sim_setup

    monkeypatch.setattr(
        "app.services.chat.openai.chat.completions.create",
        _make_openai_mock('{"unexpected": "shape"}'),
    )

    result = asyncio.run(
        process_chat_message(
            user_message="do a backflip",
            sim_only=None,
            **chat_inputs,
        )
    )

    assert result["type"] == "chat_response"
    assert result["waypoints"] == []
    assert dispatcher.commands == []
    assert "Try saying" in result["content"]


def test_saved_pose_action_dispatches_directly(
    monkeypatch: pytest.MonkeyPatch, sim_setup, chat_inputs
):
    """The execute_saved_pose action bypasses primitive resolution and
    dispatches stored joints."""
    sim, dispatcher = sim_setup

    # Seed a pose into the in-memory store.
    from app.data.pose_db import save_pose

    save_pose("wave", {"r_sho_pitch": 0.785, "l_sho_pitch": -0.785})

    plan = MotionPlan(
        action="execute_saved_pose",
        pose_name="wave",
        verbal_response="Here's your wave pose!",
        satisfied=True,
    )
    monkeypatch.setattr(
        "app.services.chat.openai.chat.completions.create",
        _make_openai_mock(plan.model_dump_json()),
    )

    result = asyncio.run(
        process_chat_message(
            user_message="show me my wave pose",
            sim_only=None,
            **chat_inputs,
        )
    )

    assert result["type"] == "chat_response"
    servo_ids = {cmd.servo_id for cmd in dispatcher.commands}
    assert servo_ids == {13, 14}  # l_sho_pitch, r_sho_pitch
