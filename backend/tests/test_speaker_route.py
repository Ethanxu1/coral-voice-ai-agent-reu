"""Tests for the TTS speaker endpoint."""

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


def test_speak_returns_audio_bytes(client):
    response = client.post("/speak", json={"text": "Hello!"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"fake-mp3"


def test_speak_missing_text_returns_422(client):
    response = client.post("/speak", json={})
    assert response.status_code == 422


def test_speaker_health_reports_enabled(client):
    response = client.get("/speak/health")
    assert response.status_code == 200
    assert response.json()["tts_enabled"] is True
