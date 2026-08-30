"""Tests for health and readiness endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import tts as tts_module


class _FakeSpeechResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content


class _FakeSpeech:
    def create(self, **kwargs):
        return _FakeSpeechResponse(b"fake-mp3")


class _FakeAudio:
    def __init__(self) -> None:
        self.speech = _FakeSpeech()


class _FakeOpenAIClient:
    def __init__(self) -> None:
        self.audio = _FakeAudio()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(tts_module, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(tts_module, "TTS_IS_ENABLED", True)
    monkeypatch.setattr(tts_module, "_client", _FakeOpenAIClient())
    monkeypatch.setattr(tts_module, "_get_client", lambda: _FakeOpenAIClient())

    app = create_app()
    with TestClient(app) as c:
        yield c

    tts_module.invalidate_client()


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_reports_required_components(client):
    response = client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["assets_present"] is True
    assert data["whisper_ready"] is True
    assert data["tts_enabled"] is True
    assert data["tts_key_present"] is True
    assert data["db_writable"] is True
