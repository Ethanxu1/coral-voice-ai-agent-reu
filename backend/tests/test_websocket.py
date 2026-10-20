"""Tests for the /ws message handlers (commands and chat routing)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.routes import websocket as ws_routes
from app.main import create_app
from app.services import tts as tts_module

pytestmark = pytest.mark.db


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    # No OpenAI calls: replies stay text-only.
    monkeypatch.setattr(tts_module, "generate_speech", lambda text: None)
    with TestClient(create_app()) as c:
        yield c


def test_jog_command_returns_result_with_joint_states(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "command", "command": "head_left"})
        result = ws.receive_json()
    assert result["type"] == "command_result"
    assert result["success"] is True
    assert result["command"] == "head_left"
    assert "head_pan" in result["joint_states"]


def test_unknown_message_type_keeps_connection_open(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "bogus"})
        ws.send_json({"type": "command", "command": "not_a_command"})
        result = ws.receive_json()
    assert result == {
        "type": "command_result",
        "success": False,
        "command": "not_a_command",
        "collision_clamped": False,
        "fall_blocked": False,
        "bad_pairs": [],
        "joint_states": None,
    }


def test_chat_goes_through_hybrid_classifier(client, monkeypatch):
    """Typed chat uses the same intent classifier as /classify-intent."""
    seen: list[str] = []

    def fake_classify(text, **kwargs):
        seen.append(text)
        return {"type": "conversation", "classifier": "test"}

    async def fake_conversation(user_message, **kwargs):
        return {"type": "chat_response", "role": "assistant", "content": f"echo: {user_message}"}

    monkeypatch.setattr(ws_routes, "classify_intent", fake_classify)
    monkeypatch.setattr(ws_routes, "process_conversation_message", fake_conversation)

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "chat", "content": "what is your favorite color?"})
        reply = ws.receive_json()

    assert seen == ["what is your favorite color?"]
    assert reply["type"] == "chat_response"
    assert reply["content"] == "echo: what is your favorite color?"


@pytest.fixture
def dispatched(monkeypatch):
    """Record servo dispatches from /ws instead of moving the sim."""
    calls: list[tuple[list, bool | None]] = []

    async def record(commands, sim_only=None):
        calls.append((commands, sim_only))

    monkeypatch.setattr(ws_routes, "dispatch_servo_commands", record, raising=False)
    return calls


def test_jog_glides_instead_of_snapping(client, dispatched):
    """A jog is sent as a timed move, like every other motion — it must not
    write the new target straight into the sim (which snaps the joint)."""
    from app.robot.angle_utils import rad_to_servo_units
    from app.state import state

    start = state.simulator.get_joint_position("head_pan")
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "command", "command": "head_left"})
        result = ws.receive_json()

    assert result["success"] is True
    assert state.simulator.get_joint_position("head_pan") == pytest.approx(start)
    [(commands, _)] = dispatched
    [cmd] = commands
    assert cmd.servo_id == 23  # head_pan
    assert cmd.position == rad_to_servo_units(start - state.simulator.STEP_SIZE)
    assert cmd.duration_ms >= 300


def test_jog_is_safety_checked_before_it_moves(client, dispatched, monkeypatch):
    """The collision/fall gate runs on the jog target first; only its safe
    target is dispatched, and the verdict reaches the client."""
    from app.robot.angle_utils import rad_to_servo_units
    from app.state import state

    start = state.simulator.get_joint_position("head_pan")
    report = {"collision_clamped": True, "fall_blocked": False, "bad_pairs": ["a/b"]}
    monkeypatch.setattr(
        ws_routes,
        "collision_checked_targets",
        lambda sim, targets, context: ({"head_pan": start - 0.05}, report),
        raising=False,
    )
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "command", "command": "head_left"})
        result = ws.receive_json()

    assert result["collision_clamped"] is True
    assert result["bad_pairs"] == ["a/b"]
    [(commands, _)] = dispatched
    assert [c.position for c in commands] == [rad_to_servo_units(start - 0.05)]
