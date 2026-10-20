"""Tests for the /ws message handlers (commands and chat routing)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.routes import websocket as ws_routes
from app.main import create_app
from app.services import tts as tts_module


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
