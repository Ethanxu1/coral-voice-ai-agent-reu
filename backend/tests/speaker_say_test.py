"""Same test as speaker_test.py but using macOS's built-in `say` command
instead of pyttsx3, to compare TTS/playback behavior against the pyttsx3 path.
"""
import os
import subprocess
import tempfile

import soundfile as sf
import sounddevice as sd

_SCRATCH_AIFF = os.path.join(tempfile.gettempdir(), f"coral_speak_say_{os.getpid()}.aiff")

subprocess.run(["say", "-o", _SCRATCH_AIFF, "hellow, i am this man who likes to get under tables"], check=True)

# `say -o` writes AIFF regardless of the output extension; soundfile reads it fine.
data, samplerate = sf.read(_SCRATCH_AIFF, dtype="int16")
print("speaking")
sd.play(data, samplerate)
sd.wait()
print("done")
