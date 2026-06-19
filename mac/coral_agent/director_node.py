"""Director node (Mac) — the demo state machine.

Orchestrates the whole experience by calling services on the Pi (vision, body)
and on the Mac (speaker, audio) over rosbridge, and by exchanging UI commands /
results with the browser frontend via topics.

Flow:  INTRO -> (LOOP_START -> RECORD) x N -> OUTRO

Each external step is a BLOCKING service call, so the Director advances only when
the previous action has actually finished (speech done, motion held, etc.).

NOTE (skeleton): the wave / thumbs-up flourishes are stubbed, and the RECORD
step expects the frontend to capture mic audio, call AudioToAction, and publish
the result on /demo/audio_result.
"""
from __future__ import annotations

import json
import threading
import time

import roslibpy
from loguru import logger

from coral_agent import states
from coral_agent.rosbridge import (
    connect,
    SRV_SPEAK, SRV_CLASSIFY, SRV_WATCH_GESTURE, SRV_EXECUTE_BODY,
    TOPIC_DEMO_STATE, TOPIC_DEMO_COMMAND, TOPIC_AUDIO_RESULT,
)

# How long to wait for a single voice "fix my pose" result before re-prompting.
AUDIO_RESULT_TIMEOUT = 30.0


class Director:
    def __init__(self, client: roslibpy.Ros):
        self.client = client
        self.state_pub = roslibpy.Topic(client, TOPIC_DEMO_STATE, "std_msgs/String")
        self.cmd_pub = roslibpy.Topic(client, TOPIC_DEMO_COMMAND, "std_msgs/String")
        self.state_pub.advertise()
        self.cmd_pub.advertise()

        # frontend posts the voice-adjust result here after recording
        self._audio_result: dict | None = None
        self._audio_event = threading.Event()
        self.audio_sub = roslibpy.Topic(client, TOPIC_AUDIO_RESULT, "std_msgs/String")
        self.audio_sub.subscribe(self._on_audio_result)

    # ── rosbridge helpers ─────────────────────────────────────────────────────
    def _call(self, name: str, srv_type: str, args: dict | None = None, timeout: float | None = None) -> dict:
        service = roslibpy.Service(self.client, name, srv_type)
        return service.call(roslibpy.ServiceRequest(args or {}), timeout=timeout)

    def _publish_state(self, state: states.DemoState, **extra) -> None:
        payload = {"state": state.value, **extra}
        self.state_pub.publish(roslibpy.Message({"data": json.dumps(payload)}))
        logger.info(f"state -> {state.value} {extra if extra else ''}")

    def _command(self, **payload) -> None:
        self.cmd_pub.publish(roslibpy.Message({"data": json.dumps(payload)}))

    def _speak(self, text: str) -> None:
        self._call(SRV_SPEAK, "coral_demo/Speak", {"text": text})

    def _on_audio_result(self, msg) -> None:
        try:
            self._audio_result = json.loads(msg["data"])
        except (ValueError, KeyError):
            self._audio_result = None
        self._audio_event.set()

    # ── states ────────────────────────────────────────────────────────────────
    def intro(self) -> None:
        self._publish_state(states.DemoState.INTRO)
        self._speak(states.INTRO_LINES)
        self._command(action="wave")           # TODO: real wave pose on the robot
        # advance when the subject crosses their hands
        self._command(action="await_gesture", gesture=states.PROGRESSION_GESTURE)
        self._call(SRV_WATCH_GESTURE, "coral_demo/WatchForGesture",
                   {"gesture": states.PROGRESSION_GESTURE, "timeout": 0.0})

    def countdown(self) -> None:
        for n in states.COUNTDOWN:
            self._command(action="countdown", value=n)
            self._speak(n)          # blocks until spoken
            time.sleep(1.0)

    def loop_iteration(self, index: int) -> None:
        self._publish_state(states.DemoState.LOOP_START, iteration=index)
        self._speak(states.LOOP_START_LINES if index == 0 else states.LOOP_AGAIN_LINES)
        self.countdown()

        # camera click + classify the current pose
        self._command(action="camera_click")
        result = self._call(SRV_CLASSIFY, "coral_demo/ClassifyFrame", {})
        self._publish_state(states.DemoState.LOOP_START, iteration=index,
                            move=result.get("move"), confidence=result.get("confidence"))
        # robot mimics (dev mode: returns to stand), holding the pose then standing
        self._call(SRV_EXECUTE_BODY, "coral_demo/ExecuteBody",
                   {"move": result.get("move", "stand"), "duration_ms": 800, "return_to_stand": True})

        self.record(index)

    def record(self, index: int) -> None:
        self._publish_state(states.DemoState.RECORD, iteration=index)
        self._speak(states.RECORD_LINES)

        while True:
            self._audio_event.clear()
            self._command(action="record")     # frontend records + calls AudioToAction
            got = self._audio_event.wait(AUDIO_RESULT_TIMEOUT)
            res = self._audio_result if got else None
            if not res:
                logger.warning("no audio result — re-prompting")
                continue

            self._speak(res.get("verbal_response", ""))
            if res.get("has_action"):
                self._call(SRV_EXECUTE_BODY, "coral_demo/ExecuteBody", {
                    "move": "",
                    "servo_ids": res.get("servo_ids", []),
                    "positions": res.get("positions", []),
                    "duration_ms": res.get("duration_ms", 1000),
                    "return_to_stand": True,
                })
                self._command(action="record_done")
                return
            # clarification question — record again

    def outro(self) -> None:
        self._publish_state(states.DemoState.OUTRO)
        self._speak(states.OUTRO_LINES)

    def run(self) -> None:
        self.intro()
        for i in range(states.LOOP_REPEATS):
            self.loop_iteration(i)
        self.outro()
        logger.info("demo complete")


def main() -> None:
    client = connect()
    try:
        Director(client).run()
    finally:
        client.terminate()


if __name__ == "__main__":
    main()
