"""Audio node (Mac) — Whisper transcription + LLM motion planning over rosbridge.

Advertises the coral_demo/AudioToAction service: given base64 webm mic audio (and
the current joint state for context), it transcribes with faster-whisper, plans a
motion with the router LLM, and returns SAFE, already-clamped explicit servo
targets that the Director hands to body_node's ExecuteBody.

`has_action` is false when the LLM asks a clarification question instead of moving.

NOTE (skeleton): multi-step sequences and parallel groups are flattened into a
single merged pose. Per-step / parallel execution is a TODO once the basic loop
works end to end.
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
import time
from pathlib import Path

import roslibpy
from loguru import logger
from openai import OpenAI

from coral_agent import primitives, validation
from coral_agent.angle_utils import speed_to_duration_ms
from coral_agent.config import LLM_MODEL
from coral_agent.hardware_angle_utils import rad_to_hardware_units
from coral_agent.rosbridge import connect, SRV_AUDIO_TO_ACTION
from coral_agent.servo_config import SERVO_ID_MAP

_ROUTER_PROMPT = (Path(__file__).parent / "prompts" / "router.md").read_text(encoding="utf-8")
_openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), base_url=os.getenv("OPENAI_BASE_URL") or None)
_whisper = None


def _get_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        logger.info("loading Whisper (base)...")
        _whisper = WhisperModel("base", device="cpu", compute_type="int8")
    return _whisper


def transcribe(audio_bytes: bytes) -> str:
    model = _get_whisper()
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        f.write(audio_bytes)
        tmp = f.name
    try:
        segments, _ = model.transcribe(tmp, language="en", no_speech_threshold=0.6)
        return " ".join(s.text.strip() for s in segments if s.no_speech_prob < 0.6).strip()
    finally:
        Path(tmp).unlink(missing_ok=True)


def plan_motion(transcript: str, state_json: str) -> dict:
    """Call the router LLM, return parsed {verbal_response, waypoints}."""
    contextual = (
        f"CURRENT_STATE: {state_json or '{}'}\n"
        f"STATE_DESCRIPTION: \n\n"
        f"USER_REQUEST: {transcript}"
    )
    resp = _openai.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": _ROUTER_PROMPT},
            {"role": "user", "content": contextual},
        ],
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)


def _merge_entry(merged: dict, entry: dict, speed_ref: list) -> None:
    for pname in entry.get("primitives", []):
        res = primitives.resolve_primitive(
            pname, entry.get("angle"), entry.get("direction"), entry.get("speed"),
        )
        if res is None:
            continue
        joints, final_speed, _ = res
        merged.update(joints)
        speed_ref[0] = entry.get("speed") or final_speed


def plan_to_servos(plan: dict) -> tuple[list[int], list[int], int]:
    """Flatten a plan into clamped explicit servo targets. (skeleton: merges all
    steps into one pose; see module note.)"""
    merged: dict[str, float] = {}
    speed_ref = [1.0]
    for entry in plan.get("waypoints", []):
        if "parallel" in entry:
            for track in entry["parallel"]:
                for raw in track.get("track", []):
                    _merge_entry(merged, raw, speed_ref)
        else:
            _merge_entry(merged, entry, speed_ref)

    if not merged:
        return [], [], speed_to_duration_ms(speed_ref[0])

    safe = validation.validate_waypoint(merged, clamp=True).validated_joints
    servo_ids, positions = [], []
    for name, rad in safe.items():
        if name not in SERVO_ID_MAP:
            continue
        servo_ids.append(SERVO_ID_MAP[name])
        positions.append(rad_to_hardware_units(rad, name))
    return servo_ids, positions, speed_to_duration_ms(speed_ref[0])


def handle(request, response) -> bool:
    audio_b64 = request.get("audio_b64", "")
    state_json = request.get("state_json", "{}")
    try:
        transcript = transcribe(base64.b64decode(audio_b64)) if audio_b64 else ""
        logger.info(f"heard: {transcript!r}")
        plan = plan_motion(transcript, state_json) if transcript else {"verbal_response": "", "waypoints": []}
        servo_ids, positions, duration_ms = plan_to_servos(plan)

        response["transcript"] = transcript
        response["verbal_response"] = plan.get("verbal_response", "")
        response["has_action"] = bool(servo_ids)
        response["servo_ids"] = servo_ids
        response["positions"] = positions
        response["duration_ms"] = duration_ms
    except Exception as e:  # never let a bad request kill the service
        logger.exception("audio_to_action failed")
        response["transcript"] = ""
        response["verbal_response"] = "Sorry, I had trouble with that."
        response["has_action"] = False
        response["servo_ids"] = []
        response["positions"] = []
        response["duration_ms"] = 1000
    return True


def main() -> None:
    client = connect()
    service = roslibpy.Service(client, SRV_AUDIO_TO_ACTION, "coral_demo/AudioToAction")
    service.advertise(handle)
    logger.info(f"audio advertised {SRV_AUDIO_TO_ACTION}")
    try:
        while client.is_connected:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        service.unadvertise()
        client.terminate()


if __name__ == "__main__":
    main()
