# /// script
# requires-python = ">=3.12"
# dependencies = ["elevenlabs>=2", "python-dotenv>=1"]
# ///
"""Generate CORAL's Rock Paper Scissors voice clips with ElevenLabs.

The game only says a fixed set of lines (frontend/src/rps/voiceLines.json), so
they are generated once and shipped as MP3s in frontend/public/rps/voice/:
instant playback, no API key or network at play time, any OS. Re-run this after
changing a line.

    uv run backend/tools/generate_rps_voice.py                  # missing clips only
    uv run backend/tools/generate_rps_voice.py --force          # regenerate all
    uv run backend/tools/generate_rps_voice.py --only hello got_it
    uv run backend/tools/generate_rps_voice.py --voice <id> --only hello --out /tmp/try

Needs ELEVENLABS_API_KEY in the environment or the repo's .env (a key with
text-to-speech permission is enough).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from elevenlabs import ElevenLabs, VoiceSettings

ROOT = Path(__file__).resolve().parents[2]
LINES = ROOT / "frontend/src/rps/voiceLines.json"
OUT = ROOT / "frontend/public/rps/voice"

# CORAL's voice. Eleven v4 is ElevenLabs' highest-quality model; latency
# doesn't matter here since the clips are made ahead of time.
VOICE_ID = "cgSgspJ2msm6clMCkdW9"
MODEL_ID = "eleven_v4"
# Fairly steady: at 0.45 Eleven v4 changed its tone from sentence to sentence
# within one line ("I picked Rock." flat, "You got me!" excited), which sounded odd.
SETTINGS = VoiceSettings(stability=0.7, similarity_boost=0.75)
FORMAT = "mp3_44100_128"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="+", metavar="ID", help="line ids to generate")
    parser.add_argument("--force", action="store_true", help="regenerate clips that already exist")
    parser.add_argument("--voice", default=VOICE_ID, help="ElevenLabs voice id")
    parser.add_argument("--out", type=Path, default=OUT, help="output folder")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    lines: dict[str, str] = json.loads(LINES.read_text())
    unknown = set(args.only or []) - set(lines)
    if unknown:
        parser.error(f"unknown line ids: {', '.join(sorted(unknown))}")

    args.out.mkdir(parents=True, exist_ok=True)
    # The SDK reads ELEVENLABS_API_KEY when it is imported, before .env is loaded: pass it.
    client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))
    chars = 0
    for line_id in args.only or lines:
        path = args.out / f"{line_id}.mp3"
        if path.exists() and not args.force and not args.only:
            continue
        text = lines[line_id]
        audio = client.text_to_speech.convert(
            voice_id=args.voice,
            text=text,
            model_id=MODEL_ID,
            voice_settings=SETTINGS,
            output_format=FORMAT,
        )
        path.write_bytes(b"".join(audio))
        chars += len(text)
        print(f"{line_id}: {path.stat().st_size // 1024} KB  {text!r}")
    print(f"done: {chars} characters sent")


if __name__ == "__main__":
    main()
