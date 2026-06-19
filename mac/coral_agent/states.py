"""Demo state machine definitions: the ordered states, the spoken lines, and
tunable config (loop repeats, progression gesture)."""
from __future__ import annotations

import os
from enum import Enum


class DemoState(str, Enum):
    INTRO = "intro"
    LOOP_START = "loop_start"   # "let's learn a move" + 3-2-1 countdown + classify
    RECORD = "record"           # "tell me how to fix my pose" + voice adjust
    OUTRO = "outro"


# How many times the LOOP_START -> RECORD pair repeats (spec: configurable N).
LOOP_REPEATS = int(os.getenv("DEMO_LOOP_REPEATS", "2"))

# Progression gesture the vision node watches for to advance out of the intro.
PROGRESSION_GESTURE = "hands_close"

# Seconds the body holds a mimicked pose before returning to stand.
POSE_HOLD_SECONDS = 3.0

# ── Spoken lines ──────────────────────────────────────────────────────────────
INTRO_LINES = (
    "Hello, my name is Robert. Today, I want you to help me learn how to do some moves. "
    "First, I want you to strike your favorite pose. If you need some suggestions, "
    "here are some below. Cross your hands when you are ready."
)

LOOP_START_LINES = (
    "Alright, now I am going to take a picture of you doing that pose, and I will try to "
    "replicate it. Then, you can tell me how to fix it. Ready?"
)

# Said one at a time, synced with the UI countdown.
COUNTDOWN = ["3", "2", "1"]

RECORD_LINES = (
    "Now I need your help to make my moves even better. Please tell me how I can fix my pose."
)

LOOP_AGAIN_LINES = (
    "Alright, great job! Now I want to learn another move, so let's try the same thing again. Ready?"
)

OUTRO_LINES = (
    "Thank you! You might be wondering how I knew which move to do. I have a special machine "
    "called a machine learning model that can tell me which pose it thinks you did. It can tell me "
    "how likely each kind of pose is, and I just pick the most likely one and tell my arms and legs "
    "to do that move."
)
