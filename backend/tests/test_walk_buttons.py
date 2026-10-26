"""Website "Walk forward" / "Walk backward" / "Stop" buttons (2026-10-26).

Each click walks the real robot for BUTTON_WALK_S with its walking engine,
renewing the walk (the robot stops a walk that isn't renewed) and then
stopping it. A new click replaces the walk in progress; Stop ends it at once.
The robot side limits how far it can walk from its start
(pi/nodes/walking.py MAX_TRAVEL_M), so it can't walk off a desk.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import walk_buttons as wb
from app.state import state


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Recorder:
    def __init__(self):
        self.calls: list[tuple[bool, int]] = []

    async def __call__(self, walking: bool, direction: int = 0) -> None:
        self.calls.append((walking, direction))


@pytest.mark.anyio
async def test_a_click_walks_for_a_while_then_stops(monkeypatch):
    monkeypatch.setattr(wb, "BUTTON_WALK_S", 0.3)
    monkeypatch.setattr(wb, "KEEPALIVE_S", 0.05)
    rec = Recorder()
    buttons = wb.WalkButtons(rec)
    await buttons.start(1)
    await asyncio.sleep(0.5)
    renewals = [c for c in rec.calls if c[0]]
    assert len(renewals) >= 4 and all(d == 1 for _, d in renewals)
    assert rec.calls[-1] == (False, 0)
    assert not buttons.walking


@pytest.mark.anyio
async def test_a_new_click_replaces_the_walk_in_progress(monkeypatch):
    monkeypatch.setattr(wb, "BUTTON_WALK_S", 5.0)
    monkeypatch.setattr(wb, "KEEPALIVE_S", 0.05)
    rec = Recorder()
    buttons = wb.WalkButtons(rec)
    await buttons.start(1)
    await asyncio.sleep(0.12)
    await buttons.start(-1)
    await asyncio.sleep(0.12)
    assert rec.calls[-1] == (True, -1)
    assert (False, 0) not in rec.calls          # switching doesn't stop in between
    await buttons.stop()


@pytest.mark.anyio
async def test_stop_ends_the_walk_at_once(monkeypatch):
    monkeypatch.setattr(wb, "BUTTON_WALK_S", 5.0)
    monkeypatch.setattr(wb, "KEEPALIVE_S", 0.05)
    rec = Recorder()
    buttons = wb.WalkButtons(rec)
    await buttons.start(-1)
    await asyncio.sleep(0.12)
    await buttons.stop()
    assert rec.calls[-1] == (False, 0)
    n = len(rec.calls)
    await asyncio.sleep(0.2)
    assert len(rec.calls) == n                   # nothing renews it afterwards
    assert not buttons.walking


@pytest.mark.anyio
async def test_a_failing_robot_link_does_not_crash_the_button(monkeypatch):
    monkeypatch.setattr(wb, "BUTTON_WALK_S", 0.2)
    monkeypatch.setattr(wb, "KEEPALIVE_S", 0.05)

    async def broken(walking, direction=0):
        raise RuntimeError("robot unreachable")

    buttons = wb.WalkButtons(broken)
    await buttons.start(1)
    await asyncio.sleep(0.4)
    assert not buttons.walking


# ── HTTP routes ──────────────────────────────────────────────────────────────


class FakeButtons:
    def __init__(self):
        self.started: list[int] = []
        self.stopped = 0

    async def start(self, direction: int) -> None:
        self.started.append(direction)

    async def stop(self) -> None:
        self.stopped += 1


@pytest.fixture
def client(monkeypatch):
    fake = FakeButtons()
    monkeypatch.setattr(wb, "buttons", fake)

    async def no_status():
        return {}

    monkeypatch.setattr(wb, "robot_walk_status", no_status)
    return TestClient(create_app()), fake


def test_walk_route_starts_a_walk_on_the_robot(client, monkeypatch):
    http, fake = client
    monkeypatch.setattr(state, "robot_mode", "robot")
    r = http.post("/walk/step", json={"direction": 1})
    assert r.status_code == 200 and r.json()["walking"] == "forward"
    r = http.post("/walk/step", json={"direction": -1})
    assert r.json()["walking"] == "backward"
    assert fake.started == [1, -1]


def test_walk_route_only_accepts_forward_or_backward(client, monkeypatch):
    http, fake = client
    monkeypatch.setattr(state, "robot_mode", "robot")
    assert http.post("/walk/step", json={"direction": 0}).status_code == 422
    assert http.post("/walk/step", json={"direction": 5}).status_code == 422
    assert fake.started == []


def test_walk_route_explains_the_simulator_cannot_walk(client, monkeypatch):
    http, fake = client
    monkeypatch.setattr(state, "robot_mode", "sim")
    r = http.post("/walk/step", json={"direction": 1})
    assert r.status_code == 409 and "real robot" in r.json()["detail"]
    assert fake.started == []


def test_stop_route_always_stops(client, monkeypatch):
    http, fake = client
    monkeypatch.setattr(state, "robot_mode", "sim")
    assert http.post("/walk/stop").status_code == 200
    assert fake.stopped == 1



def _walking_module():
    import importlib
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "robot" / "pi" / "nodes"))
    return importlib.import_module("walking")


def test_the_reset_time_shown_matches_the_robot():
    assert wb.TRAVEL_RESET_S == _walking_module().HEADING_KEEP_S


def test_one_click_walks_visibly_and_fits_inside_the_robots_travel_limit():
    """2026-10-26: 2 s of 1 cm steps couldn't be told apart from marching in
    place. A click is longer with bigger steps -- but must not run into the
    robot's own travel limit, or it would march in place for the rest of it."""
    walking = _walking_module()
    assert wb.BUTTON_WALK_S == 4.0 and walking.WALK_STEP_M == 0.01
    estimated = wb.BUTTON_WALK_S * walking.WALK_STEP_M * walking.STEPS_PER_S
    assert estimated < walking.MAX_TRAVEL_M


# ── Travel feedback (2026-10-26) ─────────────────────────────────────────────
# Repeated "Walk forward" clicks reached the robot's travel limit and it
# silently marched in place. The website now says how far it has walked and
# what to do at the limit.


def test_travel_message_reports_progress():
    status = {"travel_m": 0.07, "max_travel_m": 0.20}
    assert wb.travel_message(status, 1) == "Walked 7 of 20 cm forward so far."
    status = {"travel_m": -0.04, "max_travel_m": 0.20}
    assert wb.travel_message(status, -1) == "Walked 4 of 20 cm backward so far."


def test_travel_message_explains_the_limit():
    status = {"travel_m": 0.20, "max_travel_m": 0.20}
    msg = wb.travel_message(status, 1)
    assert "limit" in msg and "Walk backward" in msg and "30 s" in msg
    # The other way is still free.
    assert "limit" not in wb.travel_message(status, -1)


def test_travel_message_is_silent_without_robot_status():
    assert wb.travel_message({}, 1) is None
    assert wb.travel_message({"available": False, "state": "idle", "yaw_deg": None}, 1) is None


def test_walk_route_returns_the_travel_note(client, monkeypatch):
    http, fake = client
    monkeypatch.setattr(state, "robot_mode", "robot")

    async def status():
        return {"travel_m": 0.20, "max_travel_m": 0.20}

    monkeypatch.setattr(wb, "robot_walk_status", status)
    r = http.post("/walk/step", json={"direction": 1})
    assert r.status_code == 200 and "limit" in r.json()["note"]
