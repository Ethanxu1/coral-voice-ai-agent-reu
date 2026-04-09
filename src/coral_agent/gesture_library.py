"""Gesture library with animated social gestures mapped from robotics research.

This library contains gestures adapted from:
- SoftBank Pepper robot animations (pepper-core-anims)
- Social robotics research on communicative gestures
- Standard human gesture patterns

Joint mapping (Pepper → Apollo):
- HeadPitch → neck_pitch (same sign: positive = down)
- HeadYaw → neck_yaw (same sign: positive = left)
- ShoulderPitch → shoulder_fe (Pepper: 90°=rest, 0°=forward → Apollo: 0=rest, negative=forward)
- ElbowRoll → elbow (Apollo: negative = bent)

Conversion: degrees to radians = deg * π/180 ≈ deg * 0.0175
"""

from dataclasses import dataclass, field


@dataclass
class AnimatedGesture:
    """An animated gesture with multiple keyframes."""

    name: str
    description: str
    category: str
    keyframes: list[dict[str, float]]  # List of joint positions at each keyframe
    durations: list[float]  # Duration in seconds for each transition
    tags: list[str] = field(default_factory=list)


# Conversion helper
def deg_to_rad(degrees: float) -> float:
    """Convert degrees to radians."""
    return degrees * 0.0175


# ============================================================================
# GREETING GESTURES
# ============================================================================

WAVE_HELLO = AnimatedGesture(
    name="wave_hello",
    description="Friendly wave hello gesture with right hand",
    category="greeting",
    keyframes=[
        # 1. Start: Raise arm to wave position
        {
            "r_shoulder_fe": -1.2,      # Arm raised forward
            "r_shoulder_aa": -0.3,      # Slightly out
            "r_elbow": -1.3,            # Elbow bent
            "neck_yaw": 0.0,
            "neck_pitch": 0.0,
        },
        # 2. Wave right (hand moves right)
        {
            "r_shoulder_fe": -1.2,
            "r_shoulder_aa": -0.5,
            "r_elbow": -1.0,
            "neck_yaw": 0.0,
            "neck_pitch": -0.1,         # Slight look up
        },
        # 3. Wave left (hand moves left)
        {
            "r_shoulder_fe": -1.2,
            "r_shoulder_aa": -0.2,
            "r_elbow": -1.5,
            "neck_yaw": 0.0,
            "neck_pitch": -0.1,
        },
        # 4. Wave right again
        {
            "r_shoulder_fe": -1.2,
            "r_shoulder_aa": -0.5,
            "r_elbow": -1.0,
            "neck_yaw": 0.0,
            "neck_pitch": -0.1,
        },
        # 5. Wave left again
        {
            "r_shoulder_fe": -1.2,
            "r_shoulder_aa": -0.2,
            "r_elbow": -1.5,
            "neck_yaw": 0.0,
            "neck_pitch": 0.0,
        },
        # 6. Return to rest
        {
            "r_shoulder_fe": 0.0,
            "r_shoulder_aa": 0.0,
            "r_elbow": 0.0,
            "neck_yaw": 0.0,
            "neck_pitch": 0.0,
        },
    ],
    durations=[0.5, 0.25, 0.25, 0.25, 0.25, 0.5],
    tags=["wave", "hello", "hi", "greeting", "bye", "goodbye"],
)

WAVE_HELLO_LEFT = AnimatedGesture(
    name="wave_hello_left",
    description="Friendly wave hello gesture with left hand",
    category="greeting",
    keyframes=[
        # 1. Start: Raise arm to wave position
        {
            "l_shoulder_fe": -1.2,
            "l_shoulder_aa": 0.3,       # Positive = left arm out
            "l_elbow": -1.3,
            "neck_yaw": 0.0,
            "neck_pitch": 0.0,
        },
        # 2. Wave left
        {
            "l_shoulder_fe": -1.2,
            "l_shoulder_aa": 0.5,
            "l_elbow": -1.0,
            "neck_yaw": 0.0,
            "neck_pitch": -0.1,
        },
        # 3. Wave right
        {
            "l_shoulder_fe": -1.2,
            "l_shoulder_aa": 0.2,
            "l_elbow": -1.5,
            "neck_yaw": 0.0,
            "neck_pitch": -0.1,
        },
        # 4. Wave left again
        {
            "l_shoulder_fe": -1.2,
            "l_shoulder_aa": 0.5,
            "l_elbow": -1.0,
            "neck_yaw": 0.0,
            "neck_pitch": -0.1,
        },
        # 5. Wave right again
        {
            "l_shoulder_fe": -1.2,
            "l_shoulder_aa": 0.2,
            "l_elbow": -1.5,
            "neck_yaw": 0.0,
            "neck_pitch": 0.0,
        },
        # 6. Return to rest
        {
            "l_shoulder_fe": 0.0,
            "l_shoulder_aa": 0.0,
            "l_elbow": 0.0,
            "neck_yaw": 0.0,
            "neck_pitch": 0.0,
        },
    ],
    durations=[0.5, 0.25, 0.25, 0.25, 0.25, 0.5],
    tags=["wave", "hello", "hi", "greeting", "left"],
)

# ============================================================================
# HEAD GESTURES
# ============================================================================

NOD_YES = AnimatedGesture(
    name="nod_yes",
    description="Nodding head yes (agreement) - fast emphatic nods",
    category="head",
    keyframes=[
        # Start centered
        {"neck_yaw": 0.0, "neck_pitch": 0.0},
        # Nod down deeply (near max)
        {"neck_yaw": 0.0, "neck_pitch": 0.5},
        # Back up (near max up)
        {"neck_yaw": 0.0, "neck_pitch": -0.25},
        # Nod down again
        {"neck_yaw": 0.0, "neck_pitch": 0.5},
        # Back up
        {"neck_yaw": 0.0, "neck_pitch": -0.2},
        # Back to center
        {"neck_yaw": 0.0, "neck_pitch": 0.0},
    ],
    durations=[0.12, 0.12, 0.12, 0.12, 0.12, 0.15],  # Faster transitions
    tags=["nod", "yes", "agree", "affirmative", "okay"],
)

SHAKE_NO = AnimatedGesture(
    name="shake_no",
    description="Shaking head no (disagreement) - emphatic shakes",
    category="head",
    keyframes=[
        # Start centered
        {"neck_yaw": 0.0, "neck_pitch": 0.0},
        # Turn far left (near max ~92 degrees)
        {"neck_yaw": 1.6, "neck_pitch": 0.0},
        # Turn far right
        {"neck_yaw": -1.6, "neck_pitch": 0.0},
        # Turn left again
        {"neck_yaw": 1.4, "neck_pitch": 0.0},
        # Turn right again
        {"neck_yaw": -1.4, "neck_pitch": 0.0},
        # Back to center
        {"neck_yaw": 0.0, "neck_pitch": 0.0},
    ],
    durations=[0.15, 0.18, 0.18, 0.18, 0.18, 0.15],  # Smoother transitions
    tags=["shake", "no", "disagree", "negative", "deny"],
)

HEAD_TILT_CURIOUS = AnimatedGesture(
    name="head_tilt_curious",
    description="Curious head tilt to the side - like a confused dog",
    category="head",
    keyframes=[
        # Start centered
        {"neck_yaw": 0.0, "neck_pitch": 0.0},
        # Tilt head significantly to one side and look slightly up
        {"neck_yaw": 0.8, "neck_pitch": -0.15},
        # Hold the curious pose
        {"neck_yaw": 0.8, "neck_pitch": -0.15},
        # Return to center
        {"neck_yaw": 0.0, "neck_pitch": 0.0},
    ],
    durations=[0.4, 0.8, 0.5, 0.35],
    tags=["curious", "tilt", "interested", "questioning"],
)

# ============================================================================
# EMOTIONAL GESTURES
# ============================================================================

HAPPY_REACTION = AnimatedGesture(
    name="happy_reaction",
    description="Happy celebratory gesture with both arms",
    category="emotion",
    keyframes=[
        # Start position
        {
            "l_shoulder_fe": 0.0, "l_shoulder_aa": 0.0, "l_elbow": 0.0,
            "r_shoulder_fe": 0.0, "r_shoulder_aa": 0.0, "r_elbow": 0.0,
            "neck_yaw": 0.0, "neck_pitch": 0.0,
        },
        # Arms up and out
        {
            "l_shoulder_fe": -1.3, "l_shoulder_aa": 0.6, "l_elbow": -0.5,
            "r_shoulder_fe": -1.3, "r_shoulder_aa": -0.6, "r_elbow": -0.5,
            "neck_yaw": 0.0, "neck_pitch": -0.15,
        },
        # Arms higher
        {
            "l_shoulder_fe": -1.8, "l_shoulder_aa": 0.4, "l_elbow": -0.3,
            "r_shoulder_fe": -1.8, "r_shoulder_aa": -0.4, "r_elbow": -0.3,
            "neck_yaw": 0.0, "neck_pitch": -0.2,
        },
        # Slight bounce back
        {
            "l_shoulder_fe": -1.5, "l_shoulder_aa": 0.5, "l_elbow": -0.4,
            "r_shoulder_fe": -1.5, "r_shoulder_aa": -0.5, "r_elbow": -0.4,
            "neck_yaw": 0.0, "neck_pitch": -0.1,
        },
        # Return to rest
        {
            "l_shoulder_fe": 0.0, "l_shoulder_aa": 0.0, "l_elbow": 0.0,
            "r_shoulder_fe": 0.0, "r_shoulder_aa": 0.0, "r_elbow": 0.0,
            "neck_yaw": 0.0, "neck_pitch": 0.0,
        },
    ],
    durations=[0.3, 0.25, 0.2, 0.3, 0.5],
    tags=["happy", "celebration", "excited", "joy", "yay"],
)

SAD_REACTION = AnimatedGesture(
    name="sad_reaction",
    description="Sad dejected gesture - slumped posture with head hanging down",
    category="emotion",
    keyframes=[
        # Start position
        {
            "l_shoulder_fe": 0.0, "l_shoulder_aa": 0.0, "l_elbow": 0.0,
            "r_shoulder_fe": 0.0, "r_shoulder_aa": 0.0, "r_elbow": 0.0,
            "neck_yaw": 0.0, "neck_pitch": 0.0,
            "torso_pitch": 0.0,
        },
        # Slump forward, head drops down
        {
            "l_shoulder_fe": 0.3, "l_shoulder_aa": 0.15, "l_elbow": -0.4,
            "r_shoulder_fe": 0.3, "r_shoulder_aa": -0.15, "r_elbow": -0.4,
            "neck_yaw": 0.0, "neck_pitch": 0.5,  # Head down (max)
            "torso_pitch": 0.25,
        },
        # Hold sad pose, slight head shake (disappointment)
        {
            "l_shoulder_fe": 0.3, "l_shoulder_aa": 0.15, "l_elbow": -0.4,
            "r_shoulder_fe": 0.3, "r_shoulder_aa": -0.15, "r_elbow": -0.4,
            "neck_yaw": 0.4, "neck_pitch": 0.5,
            "torso_pitch": 0.25,
        },
        # Shake other direction
        {
            "l_shoulder_fe": 0.3, "l_shoulder_aa": 0.15, "l_elbow": -0.4,
            "r_shoulder_fe": 0.3, "r_shoulder_aa": -0.15, "r_elbow": -0.4,
            "neck_yaw": -0.4, "neck_pitch": 0.45,
            "torso_pitch": 0.2,
        },
        # Return to rest slowly
        {
            "l_shoulder_fe": 0.0, "l_shoulder_aa": 0.0, "l_elbow": 0.0,
            "r_shoulder_fe": 0.0, "r_shoulder_aa": 0.0, "r_elbow": 0.0,
            "neck_yaw": 0.0, "neck_pitch": 0.0,
            "torso_pitch": 0.0,
        },
    ],
    durations=[0.6, 0.5, 0.4, 0.4, 0.7],
    tags=["sad", "dejected", "disappointed", "sorry"],
)

SHRUG = AnimatedGesture(
    name="shrug",
    description="Shrugging gesture (I don't know)",
    category="emotion",
    keyframes=[
        # Start position
        {
            "l_shoulder_fe": 0.0, "l_shoulder_aa": 0.0, "l_elbow": 0.0,
            "r_shoulder_fe": 0.0, "r_shoulder_aa": 0.0, "r_elbow": 0.0,
            "neck_yaw": 0.0, "neck_pitch": 0.0,
        },
        # Raise shoulders (arms up and out, elbows bent)
        {
            "l_shoulder_fe": -0.5, "l_shoulder_aa": 0.6, "l_elbow": -1.2,
            "r_shoulder_fe": -0.5, "r_shoulder_aa": -0.6, "r_elbow": -1.2,
            "neck_yaw": 0.0, "neck_pitch": 0.0,
        },
        # Hold shrug with slight head tilt
        {
            "l_shoulder_fe": -0.5, "l_shoulder_aa": 0.7, "l_elbow": -1.3,
            "r_shoulder_fe": -0.5, "r_shoulder_aa": -0.7, "r_elbow": -1.3,
            "neck_yaw": 0.15, "neck_pitch": 0.1,
        },
        # Return to rest
        {
            "l_shoulder_fe": 0.0, "l_shoulder_aa": 0.0, "l_elbow": 0.0,
            "r_shoulder_fe": 0.0, "r_shoulder_aa": 0.0, "r_elbow": 0.0,
            "neck_yaw": 0.0, "neck_pitch": 0.0,
        },
    ],
    durations=[0.35, 0.25, 0.5, 0.4],
    tags=["shrug", "dunno", "uncertain", "maybe", "idk"],
)

THINKING = AnimatedGesture(
    name="thinking",
    description="Thinking pose - hand to chin, head tilting as if pondering",
    category="emotion",
    keyframes=[
        # Start position
        {
            "r_shoulder_fe": 0.0, "r_shoulder_aa": 0.0, "r_elbow": 0.0,
            "neck_yaw": 0.0, "neck_pitch": 0.0,
        },
        # Bring hand up to chin area
        {
            "r_shoulder_fe": -0.6, "r_shoulder_aa": 0.2, "r_elbow": -2.0,
            "neck_yaw": 0.6, "neck_pitch": 0.15,
        },
        # Look up while thinking (pondering)
        {
            "r_shoulder_fe": -0.6, "r_shoulder_aa": 0.2, "r_elbow": -2.0,
            "neck_yaw": 0.4, "neck_pitch": -0.2,
        },
        # Look other direction (considering alternatives)
        {
            "r_shoulder_fe": -0.6, "r_shoulder_aa": 0.2, "r_elbow": -2.0,
            "neck_yaw": -0.5, "neck_pitch": 0.1,
        },
        # Small nod (idea forming)
        {
            "r_shoulder_fe": -0.6, "r_shoulder_aa": 0.2, "r_elbow": -2.0,
            "neck_yaw": -0.3, "neck_pitch": 0.3,
        },
        # Return to rest
        {
            "r_shoulder_fe": 0.0, "r_shoulder_aa": 0.0, "r_elbow": 0.0,
            "neck_yaw": 0.0, "neck_pitch": 0.0,
        },
    ],
    durations=[0.5, 0.5, 0.6, 0.5, 0.4, 0.5],
    tags=["thinking", "pondering", "considering", "hmm"],
)

# ============================================================================
# ATTENTION / DIRECTING GESTURES
# ============================================================================

LOOK_AROUND = AnimatedGesture(
    name="look_around",
    description="Looking around curiously - scanning the environment",
    category="attention",
    keyframes=[
        # Start centered
        {"neck_yaw": 0.0, "neck_pitch": 0.0},
        # Look far left
        {"neck_yaw": 1.3, "neck_pitch": -0.1},
        # Look far right
        {"neck_yaw": -1.3, "neck_pitch": -0.1},
        # Look up
        {"neck_yaw": 0.0, "neck_pitch": -0.25},
        # Look down briefly
        {"neck_yaw": 0.0, "neck_pitch": 0.4},
        # Back to center
        {"neck_yaw": 0.0, "neck_pitch": 0.0},
    ],
    durations=[0.35, 0.5, 0.6, 0.35, 0.3, 0.3],
    tags=["look", "search", "curious", "scanning"],
)

ATTENTION_HERE = AnimatedGesture(
    name="attention_here",
    description="Gesture to get attention (arms up briefly)",
    category="attention",
    keyframes=[
        # Start
        {
            "l_shoulder_fe": 0.0, "l_shoulder_aa": 0.0, "l_elbow": 0.0,
            "r_shoulder_fe": 0.0, "r_shoulder_aa": 0.0, "r_elbow": 0.0,
            "neck_yaw": 0.0, "neck_pitch": 0.0,
        },
        # Arms up
        {
            "l_shoulder_fe": -1.5, "l_shoulder_aa": 0.3, "l_elbow": -0.3,
            "r_shoulder_fe": -1.5, "r_shoulder_aa": -0.3, "r_elbow": -0.3,
            "neck_yaw": 0.0, "neck_pitch": -0.1,
        },
        # Quick down
        {
            "l_shoulder_fe": -0.8, "l_shoulder_aa": 0.2, "l_elbow": -0.5,
            "r_shoulder_fe": -0.8, "r_shoulder_aa": -0.2, "r_elbow": -0.5,
            "neck_yaw": 0.0, "neck_pitch": 0.0,
        },
        # Up again
        {
            "l_shoulder_fe": -1.5, "l_shoulder_aa": 0.3, "l_elbow": -0.3,
            "r_shoulder_fe": -1.5, "r_shoulder_aa": -0.3, "r_elbow": -0.3,
            "neck_yaw": 0.0, "neck_pitch": -0.1,
        },
        # Return
        {
            "l_shoulder_fe": 0.0, "l_shoulder_aa": 0.0, "l_elbow": 0.0,
            "r_shoulder_fe": 0.0, "r_shoulder_aa": 0.0, "r_elbow": 0.0,
            "neck_yaw": 0.0, "neck_pitch": 0.0,
        },
    ],
    durations=[0.25, 0.2, 0.2, 0.2, 0.4],
    tags=["attention", "hey", "look", "here"],
)

BECKON = AnimatedGesture(
    name="beckon",
    description="Beckoning gesture (come here)",
    category="attention",
    keyframes=[
        # Start
        {
            "r_shoulder_fe": 0.0, "r_shoulder_aa": 0.0, "r_elbow": 0.0,
            "neck_yaw": 0.0, "neck_pitch": 0.0,
        },
        # Arm forward, palm up
        {
            "r_shoulder_fe": -0.8, "r_shoulder_aa": 0.0, "r_elbow": -0.5,
            "neck_yaw": 0.0, "neck_pitch": 0.0,
        },
        # Curl fingers (bend elbow more)
        {
            "r_shoulder_fe": -0.8, "r_shoulder_aa": 0.0, "r_elbow": -1.2,
            "neck_yaw": 0.0, "neck_pitch": 0.0,
        },
        # Extend again
        {
            "r_shoulder_fe": -0.8, "r_shoulder_aa": 0.0, "r_elbow": -0.5,
            "neck_yaw": 0.0, "neck_pitch": 0.0,
        },
        # Curl again
        {
            "r_shoulder_fe": -0.8, "r_shoulder_aa": 0.0, "r_elbow": -1.2,
            "neck_yaw": 0.0, "neck_pitch": 0.0,
        },
        # Return
        {
            "r_shoulder_fe": 0.0, "r_shoulder_aa": 0.0, "r_elbow": 0.0,
            "neck_yaw": 0.0, "neck_pitch": 0.0,
        },
    ],
    durations=[0.4, 0.2, 0.2, 0.2, 0.2, 0.4],
    tags=["beckon", "come", "here", "approach"],
)

# ============================================================================
# CONVERSATIONAL GESTURES
# ============================================================================

LISTENING = AnimatedGesture(
    name="listening",
    description="Attentive listening pose with head tilt and small nods",
    category="conversational",
    keyframes=[
        # Start centered
        {"neck_yaw": 0.0, "neck_pitch": 0.0},
        # Tilt head to show attention
        {"neck_yaw": 0.5, "neck_pitch": 0.1},
        # Small understanding nod
        {"neck_yaw": 0.5, "neck_pitch": 0.35},
        # Back up
        {"neck_yaw": 0.4, "neck_pitch": 0.0},
        # Another small nod
        {"neck_yaw": 0.4, "neck_pitch": 0.3},
        # Return to attentive
        {"neck_yaw": 0.3, "neck_pitch": 0.1},
    ],
    durations=[0.4, 0.3, 0.25, 0.25, 0.25, 0.3],
    tags=["listening", "attentive", "interested"],
)

ACKNOWLEDGE = AnimatedGesture(
    name="acknowledge",
    description="Quick acknowledgment nod - single emphatic nod",
    category="conversational",
    keyframes=[
        # Start
        {"neck_yaw": 0.0, "neck_pitch": 0.0},
        # Deep nod down
        {"neck_yaw": 0.0, "neck_pitch": 0.5},
        # Back to center
        {"neck_yaw": 0.0, "neck_pitch": 0.0},
    ],
    durations=[0.2, 0.25, 0.15],
    tags=["acknowledge", "okay", "got it", "understood"],
)

BOW = AnimatedGesture(
    name="bow",
    description="Polite bow gesture - formal greeting with head and torso",
    category="conversational",
    keyframes=[
        # Start
        {
            "neck_yaw": 0.0, "neck_pitch": 0.0,
            "torso_pitch": 0.0,
        },
        # Bow down deeply
        {
            "neck_yaw": 0.0, "neck_pitch": 0.5,  # Head down max
            "torso_pitch": 0.4,  # Torso forward
        },
        # Hold bow
        {
            "neck_yaw": 0.0, "neck_pitch": 0.5,
            "torso_pitch": 0.4,
        },
        # Rise back up
        {
            "neck_yaw": 0.0, "neck_pitch": 0.0,
            "torso_pitch": 0.0,
        },
    ],
    durations=[0.6, 0.4, 0.7, 0.6],
    tags=["bow", "polite", "respect", "greeting", "formal"],
)

# ============================================================================
# GESTURE REGISTRY
# ============================================================================

GESTURE_LIBRARY: dict[str, AnimatedGesture] = {
    # Greetings
    "wave_hello": WAVE_HELLO,
    "wave_hello_left": WAVE_HELLO_LEFT,
    # Head gestures
    "nod_yes": NOD_YES,
    "shake_no": SHAKE_NO,
    "head_tilt_curious": HEAD_TILT_CURIOUS,
    # Emotional
    "happy_reaction": HAPPY_REACTION,
    "sad_reaction": SAD_REACTION,
    "shrug": SHRUG,
    "thinking": THINKING,
    # Attention
    "look_around": LOOK_AROUND,
    "attention_here": ATTENTION_HERE,
    "beckon": BECKON,
    # Conversational
    "listening": LISTENING,
    "acknowledge": ACKNOWLEDGE,
    "bow": BOW,
}

# Aliases for natural language matching
GESTURE_ALIASES: dict[str, str] = {
    "wave": "wave_hello",
    "hello": "wave_hello",
    "hi": "wave_hello",
    "bye": "wave_hello",
    "goodbye": "wave_hello",
    "yes": "nod_yes",
    "nod": "nod_yes",
    "no": "shake_no",
    "shake": "shake_no",
    "happy": "happy_reaction",
    "celebrate": "happy_reaction",
    "yay": "happy_reaction",
    "sad": "sad_reaction",
    "sorry": "sad_reaction",
    "dunno": "shrug",
    "idk": "shrug",
    "think": "thinking",
    "hmm": "thinking",
    "come here": "beckon",
    "come": "beckon",
    "okay": "acknowledge",
    "ok": "acknowledge",
    "got it": "acknowledge",
}


def get_gesture(name: str) -> AnimatedGesture | None:
    """Get a gesture by name or alias.

    Args:
        name: Gesture name or alias

    Returns:
        AnimatedGesture if found, None otherwise
    """
    normalized = name.lower().strip()

    # Direct lookup
    if normalized in GESTURE_LIBRARY:
        return GESTURE_LIBRARY[normalized]

    # Alias lookup
    if normalized in GESTURE_ALIASES:
        return GESTURE_LIBRARY.get(GESTURE_ALIASES[normalized])

    # Tag search
    for gesture in GESTURE_LIBRARY.values():
        if normalized in gesture.tags:
            return gesture

    return None


def get_all_gestures() -> list[AnimatedGesture]:
    """Get all available gestures."""
    return list(GESTURE_LIBRARY.values())


def get_gestures_by_category(category: str) -> list[AnimatedGesture]:
    """Get gestures filtered by category."""
    return [g for g in GESTURE_LIBRARY.values() if g.category == category]
