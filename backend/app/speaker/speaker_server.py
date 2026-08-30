"""Speaker server (Mac side) — blocking text-to-speech for the Director demo.

A lightweight FastAPI server wrapping ``pyttsx3`` + ``sounddevice``. The Demo
page hits ``POST /speak`` to read a line aloud and relies on the response
arriving *only after* the speech has fully finished — this is what lets the
UI line up the 3-2-1 countdown with the audio and step through the pipeline
deterministically.

Why not just call ``engine.say()`` + ``engine.runAndWait()`` directly?
On macOS, pyttsx3 drives NSSpeechSynthesizer through the Cocoa run loop, which
only pumps on the process main thread. This server does its speaking from a
worker thread (``asyncio.to_thread``, to keep FastAPI's event loop responsive),
and there BOTH ``runAndWait()`` *and* ``save_to_file()`` return immediately
without producing any audio or file — so /speak would return early (or silent).

Backend per platform:
  - **macOS**: the ``say`` CLI. It runs in its own process, so it has no
    run-loop/thread dependency and blocks until playback actually finishes.
  - **Windows/Linux**: pyttsx3 renders to a file off-thread reliably, then
    ``soundfile`` decodes it and ``sounddevice`` (PortAudio) plays + blocks on
    ``sd.wait()``. (simpleaudio was tried but segfaults on Apple Silicon / 3.12.)

A lock serializes requests so only one utterance renders/plays at a time
(pyttsx3 engines and the shared scratch WAV file aren't safe to use
concurrently).

Run with:
    uv run speaker          # listens on 0.0.0.0:5002

Environment variables:
    SPEAKER_PORT   HTTP port (default: 5002)
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import threading
from contextlib import asynccontextmanager

import pyttsx3
import sounddevice as sd
import soundfile as sf
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .scripts import SCRIPTS

# Reusable scratch file — avoids per-call tempfile create/delete churn.
# Suffixed with the pid so multiple instances on one box don't collide.
_SCRATCH_WAV = os.path.join(tempfile.gettempdir(), f"coral_speak_{os.getpid()}.wav")

_speak_lock = threading.Lock()

# Handle to the in-progress macOS `say` process so /kill can terminate it mid
# utterance. Guarded by its own lock (NOT _speak_lock) so /kill never blocks
# waiting for the current utterance to finish.
_current_proc: subprocess.Popen | None = None
_proc_lock = threading.Lock()

# macOS `say` speaking rate in words/minute (default is ~175). Bumped up so the
# demo feels snappier; override with the SAY_RATE env var.
_SAY_RATE_WPM = int(os.getenv("SAY_RATE", "220"))


def _speak_blocking(text: str) -> None:
    """Synthesize ``text`` to a scratch WAV, then play it and block until done.

    Must only ever be called with ``_speak_lock`` held — pyttsx3 engines and
    the shared scratch file are not safe for concurrent use.
    """
    global _current_proc
    if sys.platform == "darwin":
        # macOS: pyttsx3 drives NSSpeechSynthesizer through the Cocoa run loop,
        # which only pumps on the process main thread. This server speaks from a
        # worker thread (asyncio.to_thread), where BOTH runAndWait() and
        # save_to_file() return immediately without producing audio/a file. The
        # `say` CLI runs in its own process — no run-loop/thread dependency — and
        # blocks until playback actually finishes. Popen (not run) so /kill can
        # terminate it; a terminated `say` returns non-zero, which is expected.
        proc = subprocess.Popen(["say", "-r", str(_SAY_RATE_WPM), text])
        with _proc_lock:
            _current_proc = proc
        try:
            proc.wait()
        finally:
            with _proc_lock:
                if _current_proc is proc:
                    _current_proc = None
        return

    # Windows/Linux: pyttsx3 renders to a file off-thread just fine. Split synth
    # from playback so we block on the real audio buffer, not the engine.
    engine = pyttsx3.init()
    try:
        engine.save_to_file(text, _SCRATCH_WAV)
        engine.runAndWait()
    finally:
        engine.stop()
    data, samplerate = sf.read(_SCRATCH_WAV, dtype="int16")
    sd.play(data, samplerate)  # sounddevice (PortAudio) — blocks on sd.wait()
    sd.wait()


def _stop_current_speech() -> bool:
    """Terminate any in-progress utterance. Safe to call when nothing is speaking.

    Returns True if it actually stopped a running utterance. Does NOT take
    _speak_lock — it must interrupt the speaking thread, not queue behind it.
    """
    global _current_proc
    stopped = False
    with _proc_lock:
        proc, _current_proc = _current_proc, None
    if proc is not None and proc.poll() is None:
        proc.terminate()  # SIGTERM stops `say` playback immediately
        stopped = True
    # Windows/Linux playback goes through sounddevice; cut any active buffer,
    # which unblocks the speaking thread's sd.wait().
    try:
        sd.stop()
    except Exception:  # noqa: BLE001 — best-effort; nothing may be playing
        pass
    return stopped


def speak_sync(text: str, timeout: float = 60.0) -> None:
    """Thread-safe, blocking speak. Raises TimeoutError if another speak is stuck."""
    acquired = _speak_lock.acquire(timeout=timeout)
    if not acquired:
        raise TimeoutError("speech timed out waiting for the speaker to be free")
    try:
        _speak_blocking(text)
    finally:
        _speak_lock.release()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[speaker] ready — {len(SCRIPTS)} scripts loaded", flush=True)
    yield
    # best-effort cleanup of the scratch file
    try:
        os.remove(_SCRATCH_WAV)
    except OSError:
        pass


app = FastAPI(title="Coral Speaker Server", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173",
                   "http://localhost:5174", "http://127.0.0.1:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SpeakRequest(BaseModel):
    """Either raw ``text`` or a predefined ``script`` identifier (see scripts.py)."""

    text: str | None = None
    script: str | None = None


def _resolve_text(req: SpeakRequest) -> str:
    if req.script is not None:
        if req.script not in SCRIPTS:
            raise HTTPException(status_code=404, detail=f"unknown script: {req.script}")
        return SCRIPTS[req.script]
    if req.text is not None and req.text.strip():
        return req.text
    raise HTTPException(status_code=400, detail="provide either 'text' or 'script'")


@app.get("/health")
def health():
    return {"status": "ok", "scripts": sorted(SCRIPTS.keys())}


@app.get("/scripts")
def list_scripts():
    return {"scripts": SCRIPTS}


@app.post("/speak")
async def speak(req: SpeakRequest):
    """Read a line aloud and return *only after* the speech finishes."""
    text = _resolve_text(req)
    # Run the blocking work off the event loop so the server stays responsive,
    # while still not returning to the client until speech completes.
    try:
        await asyncio.to_thread(speak_sync, text)
    except TimeoutError:
        raise HTTPException(status_code=504, detail="speech timed out")
    return {"status": "done", "spoke": text}


@app.post("/kill")
async def kill():
    """Immediately stop any in-progress speech.

    Called by the demo when the tab is closed or the demo is restarted, so a
    long line (e.g. the INTRO/OUTRO) doesn't keep playing over the next run.
    """
    stopped = await asyncio.to_thread(_stop_current_speech)
    return {"status": "done", "stopped": stopped}


def main():
    port = int(os.getenv("SPEAKER_PORT", "5002"))
    # Default to localhost for school/Electron deployments; containers set CORAL_HOST=0.0.0.0.
    host = os.getenv("CORAL_HOST", "127.0.0.1")
    print(f"[speaker] starting on {host}:{port}", flush=True)
    uvicorn.run(app, host=host, port=port, reload=False)


if __name__ == "__main__":
    main()