"""Voice commands for the robot's walking engine: "march in place", "turn
left", "take 3 steps forward", "stop walking". Each walk runs a short, fixed
time and then stops (app/services/walk_commands.py); the robot's dead-man
timer (pi/nodes/walking.py) is the backstop."""

from __future__ import annotations

import asyncio

import pytest

from app.llm.intent_classifier import classify_intent_regex
from app.services import walk_commands as wc
from app.services.intent import classify_system_intent


@pytest.mark.parametrize("text,forward,turn", [
    ("march in place", 0.0, 0.0),
    ("can you march?", 0.0, 0.0),
    ("turn left", 0.0, wc.TURN_DEG),
    ("please turn to the right", 0.0, -wc.TURN_DEG),
    ("walk forward", wc.STEP_M, 0.0),
    ("take two steps forward", wc.STEP_M, 0.0),
    ("walk backwards", -wc.STEP_M, 0.0),
    ("take 3 steps backward", -wc.STEP_M, 0.0),
])
def test_walk_phrases(text, forward, turn):
    cmd = wc.parse_walk_command(text)
    assert isinstance(cmd, wc.WalkCommand)
    assert (cmd.forward, cmd.turn) == (forward, turn)


def test_step_counts_set_how_long_it_walks_within_limits():
    two = wc.parse_walk_command("take two steps forward")
    five = wc.parse_walk_command("take 5 steps forward")
    many = wc.parse_walk_command("take 40 steps forward")
    assert two.seconds < five.seconds <= many.seconds == wc.MAX_STEPS * wc.SECONDS_PER_STEP


@pytest.mark.parametrize("text", ["stop walking", "stop marching", "stop moving your legs"])
def test_stop_phrases(text):
    assert wc.parse_walk_command(text) == wc.STOP


@pytest.mark.parametrize("text", [
    "turn your head left",   # a head move
    "step back",             # undo
    "go back",               # undo
    "follow my movement",
    "raise your left arm",
    "stop following",
])
def test_other_commands_are_not_walking(text):
    assert wc.parse_walk_command(text) is None


def test_voice_routing_sends_walking_to_the_walk_handler():
    assert classify_system_intent("march in place") == "walk"
    assert classify_system_intent("turn left") == "walk"
    assert classify_system_intent("stop walking") == "walk"
    assert classify_system_intent("turn your head left") is None
    r = classify_intent_regex("march in place")
    assert r is not None and r.type == "immediate" and r.data["intent"] == "walk"
    head = classify_intent_regex("turn your head left")
    assert head is None or head.data.get("intent") != "walk"
    undo = classify_intent_regex("step back")
    assert undo is not None and undo.data.get("intent") == "undo"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_a_walk_is_renewed_then_stopped(monkeypatch):
    calls: list[tuple[bool, float, float]] = []

    async def walk_fn(walking, forward=0.0, turn=0.0):
        calls.append((walking, forward, turn))

    monkeypatch.setattr(wc, "KEEPALIVE_S", 0.02)
    await wc.start_walk(wc.WalkCommand(forward=0.0, turn=8.0, seconds=0.1, what="turning left"),
                        walk_fn)
    await asyncio.sleep(0.2)
    assert calls[0] == (True, 0.0, 8.0)
    assert 3 <= sum(1 for c in calls if c[0]) <= 7
    assert calls[-1][0] is False


@pytest.mark.anyio
async def test_stop_ends_a_walk_early_and_a_new_walk_replaces_the_old(monkeypatch):
    calls: list[tuple[bool, float, float]] = []

    async def walk_fn(walking, forward=0.0, turn=0.0):
        calls.append((walking, forward, turn))

    monkeypatch.setattr(wc, "KEEPALIVE_S", 0.02)
    await wc.start_walk(wc.WalkCommand(0.0, 0.0, 5.0, "marching"), walk_fn)
    await asyncio.sleep(0.05)
    await wc.start_walk(wc.WalkCommand(0.0, 8.0, 5.0, "turning left"), walk_fn)
    await asyncio.sleep(0.05)
    await wc.stop_walk(walk_fn)
    assert calls[-1][0] is False
    n = len(calls)
    await asyncio.sleep(0.1)
    assert len(calls) == n          # nothing renews it after the stop
    assert (True, 0.0, 8.0) in calls


@pytest.mark.anyio
async def test_in_the_simulator_a_walk_command_explains_instead_of_moving(monkeypatch):
    from app.services import intent
    from app.state import state

    started = []
    monkeypatch.setattr(state, "robot_mode", "sim")
    monkeypatch.setattr(intent, "start_walk", lambda cmd: started.append(cmd))
    reply = await intent._handle_walk("march in place")
    assert "real robot" in reply and started == []


@pytest.mark.anyio
async def test_on_the_robot_a_walk_command_starts_the_walk(monkeypatch):
    from app.services import intent
    from app.state import state

    started = []

    async def fake_start(cmd):
        started.append(cmd)

    monkeypatch.setattr(state, "robot_mode", "robot")
    monkeypatch.setattr(intent, "start_walk", fake_start)
    reply = await intent._handle_walk("turn left")
    assert started and started[0].turn == wc.TURN_DEG
    assert "turning left" in reply


def test_forward_steps_reach_the_robot_as_forward(monkeypatch):
    from app.services import motion
    from app.state import state

    seen = []
    monkeypatch.setattr(state, "robot_mode", "robot")
    monkeypatch.setattr(state, "hardware_dispatcher", type("H", (), {
        "walk": staticmethod(lambda walking, forward=0.0, turn=0.0: seen.append((walking, forward, turn)))})())
    asyncio.run(motion.set_robot_walking(True, forward=-wc.STEP_M))
    assert seen == [(True, -wc.STEP_M, 0.0)]
