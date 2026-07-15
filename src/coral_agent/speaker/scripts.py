"""Pre-programmed speaker lines for the Director demo pipeline.

Each demo state maps to a line (or short atom) the speaker server reads aloud
via pyttsx3. The Demo page requests these by identifier (``{"script": "INTRO"}``)
so the spoken script stays in one place and the UI never hard-codes copy.

The countdown digits (`"3"`, `"2"`, `"1"`) are deliberately separate atoms: the
UI speaks them one at a time and waits for each `/speak` call to return before
advancing the on-screen number, keeping audio and visuals in lockstep.
"""

# INTRO — spoken once at the start.
INTRO = (
    "Hi there! My name is Coral, and I am a robot who loves to learn. "
    "Today, I want you to help me learn some cool poses. "
)

# CLASSIFY — read up until the "3... 2... 1" countdown.
# The first time differs from the repeated times (REPEAT_CLASSIFY).
INSTRUCTIONS = (
    "First, I want you to strike your favorite pose. If you need some suggestions, here are some below. I’m going to take a picture of you doing that pose, and I’ll try to replicate it. Then, you can tell me how to fix it. Cross your arms, and I’ll count down and take a picture."
)

# RECORD — spoken before the child gives spoken feedback.
CORRECTIONS = (
    "Now I need your help to make my moves even better. Please tell me how I can fix my pose"
)

# NAME — spoken after RECORD, asks the child to name the pose.
NAME = (
    "Nice work! Now, what do you want to call that pose? "
    "Say the name out loud after the beep!"
)

# OUTRO — a short, kid-friendly explanation of how the robot "sees".
OUTRO = (
    "You might be wondering how I knew which move to do. I have a special machine that tells me where your arms and legs are in the picture, and then I use that to make my arms and legs match that pose"
)

THANK_YOU = "Thank you so much for playing with me today! Goodbye!"

# Countdown atoms — spoken individually so the UI can sync each digit.
THREE = "Three"
TWO = "Two"
ONE = "One"

# Identifier → text. Keys are the values accepted by ``POST /speak {"script": ...}``.
SCRIPTS: dict[str, str] = {
    "INTRO": INTRO,
    "INSTRUCTIONS": INSTRUCTIONS,
    "CORRECTIONS": CORRECTIONS,
    "NAME": NAME,
    "OUTRO": OUTRO,
    "THANK_YOU": THANK_YOU,
    "3": THREE,
    "2": TWO,
    "1": ONE,
}
