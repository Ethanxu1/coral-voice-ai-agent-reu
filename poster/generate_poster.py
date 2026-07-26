"""
Generate academic poster design ideas using gpt-image-1.
Run from the project root: uv run python poster/generate_poster.py
"""

import os
import base64
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

OUT_DIR = Path(__file__).parent / "generated"
OUT_DIR.mkdir(exist_ok=True)

# ── Prompts ──────────────────────────────────────────────────────────────────

HORIZONTAL_PROMPT = """
Design a professional academic research symposium poster (landscape, 48×36 inches).

PROJECT: "Interactive Pose-Matching Robot for K-12 AI Education"
AUTHORS: Ethan Xu, Scott Fukuda, Jiewen Liu, Dr. Dongkuan Xu, Dr. Peng Gao — NC State University REU 2025

COLOR SCHEME:
- Primary: NC State red (#CC0000)
- Accents: white and near-black (#111)
- Background: clean white or very light gray

LAYOUT (left to right, 3 or 4 columns):
1. Left column — NC State University logo (bold red block letters), NSF badge (blue circle), intro paragraph (2-3 short sentences), robot photo placeholder box labeled "AiNex Humanoid Robot"
2. Center-left column — "Image → Pose Pipeline" section with a clean horizontal flowchart: Camera → MediaPipe 33 Landmarks → Torso-Local Frame → Servo Units (0-1000)
3. Center-right column — "Speech → Motion Pipeline" section with a vertical flowchart: Whisper STT → Intent Classifier → GPT-4o-mini Motion Planner → MuJoCo Collision Check → Robot
4. Right column — System Architecture diagram (Laptop ⇄ WiFi ⇄ Raspberry Pi Robot), MuJoCo Simulator section, Results metrics (latency ~150ms, ~1-2s LLM, 24 DOF), Next Steps

VISUAL STYLE:
- Bold Montserrat or Barlow Condensed typography for headers
- Section headers: white text on red background bars
- Pipeline steps: small cards with red left border
- Crisp, modern academic look — not cluttered
- Placeholder image boxes with dashed borders for: robot photo, MediaPipe skeleton, web UI, MuJoCo view
- Bottom footer bar with acknowledgements text (NSF Grant No. 2244116)

The poster should look polished and ready to print at a university symposium. Clean hierarchy, plenty of white space, information-dense but not overwhelming.
""".strip()

VERTICAL_PROMPT = """
Design a professional academic research symposium poster (portrait, 36×48 inches).

PROJECT: "Interactive Pose-Matching Robot for K-12 AI Education"
AUTHORS: Ethan Xu, Scott Fukuda, Jiewen Liu, Dr. Dongkuan Xu, Dr. Peng Gao — NC State University REU 2025

COLOR SCHEME:
- Primary: NC State red (#CC0000)
- Background: white
- Text: near-black

LAYOUT (top to bottom):
- HEADER (full width): Large bold title centered on deep red (#CC0000) background, white text. NC State logo top-left, NSF logo top-right, authors below title.
- ROW 1 (two equal columns): Left = Introduction + robot photo placeholder. Right = System Architecture diagram (Laptop ⇄ WiFi ⇄ AiNex Robot with Raspberry Pi)
- ROW 2 (two equal columns): Left = "Image → Pose Pipeline" vertical flowchart (Camera → MediaPipe → Normalize → Servo Convert). Right = "Speech → Motion Pipeline" vertical flowchart (Whisper STT → Intent → LLM Planner → MuJoCo Check → Robot)
- ROW 3 (two equal columns): Left = MuJoCo Simulator (24-DOF physics model, collision detection, 3D browser visualization). Right = Results metrics in bold callout cards + Next Steps bullet list
- FOOTER: dark bar, acknowledgements text

VISUAL STYLE:
- Barlow Condensed or Montserrat for headers, clean sans-serif body
- Section headers: bold white text on red background
- Clean cards for pipeline steps with red left-side accent
- Dashed placeholder boxes for photos (robot, MediaPipe overlay, simulator view)
- Confident, modern academic design — lots of breathing room, not wall-of-text
""".strip()

DARK_PROMPT = """
Design a striking academic research symposium poster (landscape, 48×36 inches) with a bold, editorial style.

PROJECT: "Interactive Pose-Matching Robot for K-12 AI Education"
AUTHORS: Ethan Xu, Scott Fukuda, Jiewen Liu, Dr. Dongkuan Xu, Dr. Peng Gao — NC State University REU 2025

COLOR SCHEME:
- Left sidebar: deep charcoal (#1a1a1a) or very dark red (#8B0000)
- Main content: white
- Accents: bright NC State red (#CC0000) and white
- Typography on dark: white

LAYOUT:
- LEFT SIDEBAR (~25% width, dark background): NC State University name in large white condensed type, NSF badge, large bold title in white stacked vertically ("INTERACTIVE / POSE-MATCHING / ROBOT / K-12 AI"), key stats in red callout boxes (24 DOF · ~150ms · ≥85% accuracy), authors list, NSF grant acknowledgement
- MAIN AREA (~75% width, white): 2×2 grid of sections:
  Top-left: Image→Pose Pipeline (horizontal flowchart with icons)
  Top-right: Speech→Motion Pipeline (numbered step list)
  Bottom-left: System Architecture (Laptop ⇄ WiFi ⇄ Robot diagram)
  Bottom-right: MuJoCo Simulator + Results + Next Steps

VISUAL STYLE:
- Very bold, editorial feel — like a Nature or Science magazine spread
- Large condensed type for section numbers/labels
- Red accent rules and borders
- Clean icon-style illustrations for pipeline steps
- Placeholder image boxes for robot photo and diagrams
- High contrast, striking visual impact from across the room
""".strip()

# ── Generation ────────────────────────────────────────────────────────────────

DESIGNS = [
    ("horizontal_classic", HORIZONTAL_PROMPT, "1536x1024"),
    ("vertical_clean",     VERTICAL_PROMPT,   "1024x1536"),
    ("horizontal_bold",    DARK_PROMPT,        "1536x1024"),
]

def generate(name: str, prompt: str, size: str) -> Path:
    print(f"Generating: {name} ({size})...")
    response = client.images.generate(
        model="gpt-image-2",
        prompt=prompt,
        size=size,
        n=1,
    )
    image_bytes = base64.b64decode(response.data[0].b64_json)
    timestamp = datetime.now().strftime("%H%M%S")
    out_path = OUT_DIR / f"{name}_{timestamp}.png"
    out_path.write_bytes(image_bytes)
    print(f"  Saved → {out_path}")
    return out_path

if __name__ == "__main__":
    print(f"Output directory: {OUT_DIR}\n")
    for name, prompt, size in DESIGNS:
        generate(name, prompt, size)
    print("\nDone.")
