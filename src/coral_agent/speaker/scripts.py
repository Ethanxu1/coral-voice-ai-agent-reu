"""Pre-programmed speaker lines for the Director demo pipeline.

Each demo state maps to a line (or short atom) the speaker server reads aloud
via pyttsx3. The Demo page requests these by identifier (``{"script": "INTRO"}``)
so the spoken script stays in one place and the UI never hard-codes copy.

The countdown digits (`"3"`, `"2"`, `"1"`) are deliberately separate atoms: the
UI speaks them one at a time and waits for each `/speak` call to return before
advancing the on-screen number, keeping audio and visuals in lockstep.
"""

# INTRO — spoken once at the start. (Seeded from lines.py.)
INTRO = (
    "Hi there! My name is Coral, and I am a robot who loves to learn. "
    "Today, I want you to help me learn some cool poses. "
    " When you are all ready, cross your hands "
    "in front of you, and we will begin!"
)

# CLASSIFY — read up until the "3... 2... 1" countdown.
# The first time differs from the repeated times (REPEAT_CLASSIFY).
CLASSIFY_FIRST = (
    "Awesome! Now hold that pose nice and still. I am going to take a "
    "picture and try to guess what pose you are doing. Get ready!"
)

CLASSIFY_REPEAT = (
    "Great job! Let's try another one. Strike a new pose and hold it still. "
    "I'll take another picture. Ready? On three!"
)

# RECORD — spoken before the child gives spoken feedback.
RECORD = (
    "How did I do? After the beep, tell me how I can fix my pose, and I "
    "will try my best to copy you!"
)

# NAME — spoken after RECORD, asks the child to name the pose.
NAME = (
    "Nice work! Now, what do you want to call that pose? "
    "Say the name out loud after the beep!"
)

# OUTRO — a short, kid-friendly explanation of how the robot "sees".
OUTRO = (
    "That was so much fun! Here is my little secret: I learned to recognize "
    "poses by looking at thousands of pictures of people striking them. "
    "Each time, my computer brain noticed the shapes your arms and legs make, "
    "and slowly it got better and better at guessing. That is what we call "
    "machine learning. The more examples I see, the smarter I get!"
)

THANK_YOU = "Thank you so much for playing with me today! Goodbye!"

# Countdown atoms — spoken individually so the UI can sync each digit.
THREE = "Three"
TWO = "Two"
ONE = "One"

# Identifier → text. Keys are the values accepted by ``POST /speak {"script": ...}``.
SCRIPTS: dict[str, str] = {
    "INTRO": INTRO,
    "CLASSIFY_FIRST": CLASSIFY_FIRST,
    "CLASSIFY_REPEAT": CLASSIFY_REPEAT,
    "RECORD": RECORD,
    "NAME": NAME,
    "OUTRO": OUTRO,
    "THANK_YOU": THANK_YOU,
    "3": THREE,
    "2": TWO,
    "1": ONE,
}
