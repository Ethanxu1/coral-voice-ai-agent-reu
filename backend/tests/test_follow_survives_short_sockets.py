"""Follow mode must not stop when a short-lived /ws connection closes.

Reported live 2026-10-02: after one move the robot stopped following and
"follow my movement" had to be said again. The server log showed a second
/ws connection opening and closing ~0.1 s later every ~2 s, each followed by
"Follow loop cancelled". While following, the browser keeps listening and
opens a throwaway /ws per utterance just to get a transcript
(sendAudioForTranscript); the server stopped follow on ANY close. Stopping
when the page goes away is right -- that is when the LAST connection closes.
"""

from __future__ import annotations

import pytest

from app.api.routes import websocket as ws_route
from app.state import state


class _FakeFollow:
    def __init__(self):
        self.is_following = True
        self.stops: list[str | None] = []

    async def stop_follow(self, status_fn=None, reason=None, clean_logger=None):
        self.stops.append(reason)
        self.is_following = False


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def follow(monkeypatch):
    fake = _FakeFollow()
    monkeypatch.setattr(state, "follow_controller", fake)
    monkeypatch.setattr(ws_route, "connected_clients", set())
    return fake


@pytest.mark.anyio
async def test_a_throwaway_transcript_socket_closing_keeps_follow_running(follow):
    page, transcript = object(), object()
    ws_route.connected_clients.update({page, transcript})
    await ws_route._client_closed(transcript, clean_logger=None)
    assert follow.stops == []
    assert follow.is_following


@pytest.mark.anyio
async def test_follow_stops_when_the_last_connection_closes(follow):
    page = object()
    ws_route.connected_clients.add(page)
    await ws_route._client_closed(page, clean_logger=None)
    assert follow.stops == ["websocket closing"]
