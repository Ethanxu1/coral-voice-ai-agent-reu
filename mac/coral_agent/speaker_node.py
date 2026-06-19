"""Speaker node (Mac) — text-to-speech over rosbridge.

Advertises the coral_demo/Speak service. The call blocks until speech finishes,
so the Director can sequence lines and the 3-2-1 countdown against the audio.

Uses espeak (offline, lightweight). Install on macOS with:  brew install espeak
Falls back to the macOS `say` command if espeak is not on PATH. Override with
the SPEAKER_CMD env var (a format string with {text}).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time

import roslibpy
from loguru import logger

from coral_agent.rosbridge import connect, SRV_SPEAK


def _speak_command(text: str) -> list[str]:
    override = os.getenv("SPEAKER_CMD")
    if override:
        return override.format(text=text).split()
    if shutil.which("espeak"):
        return ["espeak", text]
    if shutil.which("espeak-ng"):
        return ["espeak-ng", text]
    if shutil.which("say"):  # macOS native fallback
        return ["say", text]
    raise RuntimeError("no TTS binary found — install espeak (brew install espeak)")


def speak(text: str) -> None:
    """Speak `text` and block until it finishes."""
    if not text.strip():
        return
    cmd = _speak_command(text)
    logger.info(f"speaking: {text!r}")
    subprocess.run(cmd, check=False)


def main() -> None:
    client = connect()
    service = roslibpy.Service(client, SRV_SPEAK, "coral_demo/Speak")

    def handler(request, response):
        speak(request.get("text", ""))
        response["done"] = True
        return True

    service.advertise(handler)
    logger.info(f"speaker advertised {SRV_SPEAK}")
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
