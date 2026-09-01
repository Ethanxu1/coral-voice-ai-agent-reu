"""Tests for POST /poses/extract-name (LLM name extraction with verbatim fallback)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


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


def _fake_llm(content: str):
    """Return a stand-in for openai.chat.completions.create."""

    def _create(*args, **kwargs):
        return _MockResponse(content)

    return _create


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_extracts_name_via_llm(monkeypatch: pytest.MonkeyPatch, client):
    monkeypatch.setattr(
        "app.api.routes.motion.openai.chat.completions.create",
        _fake_llm('{"name": "starfish"}'),
    )
    response = client.post("/poses/extract-name", json={"text": "let's name it starfish"})
    assert response.status_code == 200
    assert response.json() == {"name": "starfish"}


def test_llm_extracts_filler_phrase(monkeypatch: pytest.MonkeyPatch, client):
    monkeypatch.setattr(
        "app.api.routes.motion.openai.chat.completions.create",
        _fake_llm('{"name": "Buddy"}'),
    )
    response = client.post("/poses/extract-name", json={"text": "let's name it Buddy"})
    assert response.status_code == 200
    assert response.json() == {"name": "Buddy"}


def test_llm_output_is_sanitized(monkeypatch: pytest.MonkeyPatch, client):
    monkeypatch.setattr(
        "app.api.routes.motion.openai.chat.completions.create",
        _fake_llm('{"name": "Buddy!!"}'),
    )
    response = client.post("/poses/extract-name", json={"text": "call it Buddy!!"})
    assert response.status_code == 200
    assert response.json() == {"name": "Buddy"}


def test_llm_failure_falls_back_to_sanitized_verbatim(monkeypatch: pytest.MonkeyPatch, client):
    def _raise(*args, **kwargs):
        raise RuntimeError("openai unavailable")

    monkeypatch.setattr("app.api.routes.motion.openai.chat.completions.create", _raise)
    response = client.post("/poses/extract-name", json={"text": "call it super hero!"})
    assert response.status_code == 200
    assert response.json() == {"name": "call it super hero"}


@pytest.mark.parametrize("text", ["", "   "])
def test_empty_text_returns_400(monkeypatch: pytest.MonkeyPatch, client, text):
    called = False

    def _unexpected_create(*args, **kwargs):
        nonlocal called
        called = True
        return _MockResponse('{"name": "x"}')

    monkeypatch.setattr("app.api.routes.motion.openai.chat.completions.create", _unexpected_create)
    response = client.post("/poses/extract-name", json={"text": text})
    assert response.status_code == 400
    assert called is False
