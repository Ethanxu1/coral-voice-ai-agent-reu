"""Record what the camera reports while you march, and show what the march
detector makes of it.

Run while ./run.sh is up (it needs the vision server on :8001), stand where
you would for follow mode, then march in place and stop:

    .venv/bin/python scripts/march_probe.py
    .venv/bin/python scripts/march_probe.py --seconds 30

Prints twice a second: the camera's lock on you (only the locked-on person's
body is sent: "selected"; "searching" = it lost you, raise a hand for 3 s),
each thigh's angle (or which point it couldn't see), knee visibility, and
whether the detector says "marching".
Saves every frame to logs/march_probe/<time>.jsonl for replaying offline.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import websockets  # noqa: E402

from app.vision.march_detector import (  # noqa: E402
    MIN_KNEE_VISIBILITY,
    MIN_VISIBILITY,
    MarchDetector,
    thigh_raise_deg,
)

NAMES = {11: "l_shoulder", 12: "r_shoulder", 23: "l_hip", 24: "r_hip", 25: "l_knee", 26: "r_knee"}


def why_unseen(body: list[dict], side: str) -> str:
    if len(body) < 27:
        return "no body"
    knee = 25 if side == "l" else 26
    missing = [NAMES[i] for i in (11, 12, 23, 24) if body[i].get("visibility", 0) < MIN_VISIBILITY]
    if body[knee].get("visibility", 0) < MIN_KNEE_VISIBILITY:
        missing.append(NAMES[knee])
    return "unseen: " + ",".join(missing) if missing else "unseen"


def fmt(body: list[dict], side: str) -> str:
    deg = thigh_raise_deg(body, side)
    return f"{deg:5.1f}°" if deg is not None else why_unseen(body, side)


async def main(seconds: float, url: str) -> None:
    out_dir = ROOT / "logs" / "march_probe"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{datetime.now():%Y%m%d_%H%M%S}.jsonl"
    det = MarchDetector()
    frames = seen_both = 0
    t0 = time.monotonic()
    last_print = 0.0
    print(f"Recording {seconds:.0f} s to {path}. March in place, then stop.")
    async with websockets.connect(url, max_queue=8) as ws:
        with path.open("w") as f:
            while (now := time.monotonic() - t0) < seconds:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                data = json.loads(raw)
                if data.get("type") not in (None, "pose_update"):
                    continue
                body = data.get("body_landmarks") or []
                lock = data.get("selection_state", "?")
                f.write(json.dumps({"t": round(now, 3), "lock": lock, "body": body}) + "\n")
                frames += 1
                l, r = thigh_raise_deg(body, "l"), thigh_raise_deg(body, "r")
                seen_both += l is not None and r is not None
                marching = det.update(l, r, now)
                if now - last_print >= 0.5:
                    last_print = now
                    vis = [round(body[i].get("visibility", 0), 2) if len(body) > i else None
                           for i in (25, 26)]
                    print(f"{now:5.1f}s  lock {lock:<9} L thigh {fmt(body, 'l'):<28} R thigh {fmt(body, 'r'):<28}"
                          f" knee vis {vis}  {'MARCHING' if marching else '-'}")
    print(f"\n{frames} frames, both thighs readable in {seen_both} "
          f"({100 * seen_both / max(1, frames):.0f}%). Saved: {path}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seconds", type=float, default=20.0)
    p.add_argument("--url", default="ws://localhost:8001/ws/pose")
    a = p.parse_args()
    try:
        asyncio.run(main(a.seconds, a.url))
    except OSError:
        sys.exit(f"Can't reach the camera server at {a.url}. Start ./run.sh first, then rerun this.")
