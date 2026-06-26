"""Speaker server (Mac side) — blocking text-to-speech for the Director demo.

A lightweight FastAPI server wrapping ``pyttsx3``. The Demo page hits
``POST /speak`` to read a line aloud and relies on the response arriving *only
after* the speech has fully finished — this is what lets the UI line up the
3-2-1 countdown with the audio and step through the pipeline deterministically.

pyttsx3's ``runAndWait()`` is not safe to call concurrently and is fussy across
threads, so every utterance is funneled through a single dedicated worker
thread. The request handler enqueues the text and blocks on a per-request
``Event`` until the worker reports that utterance done. One engine, one worker,
no overlapping ``runAndWait`` calls.

Run with:
    uv run speaker          # listens on 0.0.0.0:5002

Environment variables:
    SPEAKER_PORT   HTTP port (default: 5002)
"""

from __future__ import annotations

import os
import queue
import threading
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel



class _SpeechJob:
    """A single utterance plus an Event the requester blocks on."""

    def __init__(self, text: str):
        self.text = text
        self.done = threading.Event()
        self.error: Exception | None = None


class SpeechWorker:
    """Single background thread that owns the pyttsx3 engine.

    All speech is serialized here: jobs are pulled off a queue one at a time and
    spoken to completion, so ``runAndWait()`` is only ever called from this one
    thread and never concurrently.
    """

    def __init__(self):
        self._queue: "queue.Queue[_SpeechJob | None]" = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="speech-worker", daemon=True)
        self._engine = None

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        import pyttsx3

        # The engine must be created and driven on this same thread.
        self._engine = pyttsx3.init()
        while True:
            job = self._queue.get()
            if job is None:  # shutdown sentinel
                break
            try:
                self._engine.say(job.text)
                self._engine.runAndWait()  # blocks until this utterance finishes
            except Exception as exc:  # noqa: BLE001 — surface to the requester
                job.error = exc
            finally:
                job.done.set()

    def speak(self, text: str, timeout: float = 60.0) -> None:
        """Enqueue ``text`` and block until it has been fully spoken."""
        job = _SpeechJob(text)
        print("put on")

        self._queue.put(job)
        print("put on")
        
    

    def stop(self) -> None:
        self._queue.put(None)


worker = SpeechWorker()


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker.start()
    print(f"[speaker] ready — {len(SCRIPTS)} scripts loaded", flush=True)
    yield
    worker.stop()


app = FastAPI(title="Coral Speaker Server", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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
    import asyncio

    text = _resolve_text(req)
    # Run the blocking wait off the event loop so the server stays responsive,
    # while still not returning to the client until speech completes.
    try:
        await asyncio.to_thread(worker.speak, text)
    except TimeoutError:
        raise HTTPException(status_code=504, detail="speech timed out")
    return {"status": "done", "spoke": text}


async def main():
    import asyncio

    wrker = SpeechWorker()

    try:
        await asyncio.to_thread(wrker.speak, "HELLLOOOOOO")
    except TimeoutError:
        raise HTTPException(status_code=504, detail="speech timed out")
    job = wrker._queue.get()
    wrker._engine.say(job.text)
    wrker._engine.runAndWait() 
    return {"status": "done", "spoke": "HELLLLOOOO"}



if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

    print("HI")

