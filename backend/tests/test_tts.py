"""Tests for the OpenAI TTS service."""

from __future__ import annotations

import pytest

from app.services import tts as tts_module
from app.services.tts import generate_speech, invalidate_client, tts_enabled


class _FakeSpeechResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content


class _FakeSpeech:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.next_response: bytes = b"fake-mp3-bytes"
        self.fail_next = False

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_next:
            raise RuntimeError("openai audio failure")
        return _FakeSpeechResponse(self.next_response)


class _FakeAudio:
    def __init__(self) -> None:
        self.speech = _FakeSpeech()


class _FakeOpenAIClient:
    def __init__(self) -> None:
        self.audio = _FakeAudio()


@pytest.fixture
def fake_openai(monkeypatch: pytest.MonkeyPatch):
    """Patch the TTS module with a fake OpenAI client and enabled state."""
    invalidate_client()
    fake_client = _FakeOpenAIClient()

    def _make_client(*args, **kwargs):
        return fake_client

    monkeypatch.setattr(tts_module, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(tts_module, "TTS_IS_ENABLED", True)
    monkeypatch.setattr(tts_module, "_client", fake_client)
    monkeypatch.setattr(tts_module, "_get_client", lambda: fake_client)

    yield fake_client

    invalidate_client()


class TestTTSEnabled:
    def test_tts_enabled_when_configured(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(tts_module, "OPENAI_API_KEY", "sk-test")
        monkeypatch.setattr(tts_module, "TTS_IS_ENABLED", True)
        assert tts_enabled() is True

    def test_tts_disabled_without_key(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(tts_module, "OPENAI_API_KEY", "")
        monkeypatch.setattr(tts_module, "TTS_IS_ENABLED", True)
        assert tts_enabled() is False

    def test_tts_disabled_when_flag_false(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(tts_module, "OPENAI_API_KEY", "sk-test")
        monkeypatch.setattr(tts_module, "TTS_IS_ENABLED", False)
        assert tts_enabled() is False


class TestGenerateSpeech:
    def test_generates_audio(self, fake_openai):
        result = generate_speech("Hello there!")
        assert result == b"fake-mp3-bytes"
        assert len(fake_openai.audio.speech.calls) == 1
        call = fake_openai.audio.speech.calls[0]
        assert call["model"] == "tts-1"
        assert call["voice"] == "nova"
        assert call["input"] == "Hello there!"

    def test_empty_text_returns_none(self, fake_openai):
        assert generate_speech("") is None
        assert generate_speech("   ") is None
        assert fake_openai.audio.speech.calls == []

    def test_long_text_truncated(self, fake_openai, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(tts_module, "TTS_MAX_CHARS", 10)
        result = generate_speech("This is a very long sentence.")
        assert result == b"fake-mp3-bytes"
        assert fake_openai.audio.speech.calls[0]["input"] == "This is a "

    def test_openai_failure_returns_none(self, fake_openai):
        fake_openai.audio.speech.fail_next = True
        assert generate_speech("Hello") is None
