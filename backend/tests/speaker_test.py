import os
import pyttsx3
import soundfile as sf
import tempfile
import sounddevice as sd

_SCRATCH_WAV = os.path.join(tempfile.gettempdir(), f"coral_speak_{os.getpid()}.wav")

engine = pyttsx3.init()
try:
    engine.save_to_file("hellow", _SCRATCH_WAV)
    engine.runAndWait()  # just flushes the file write here, not audio playback
finally:
    engine.stop()

# Decode with soundfile — pyttsx3 writes WAV on Windows/Linux but AIFF on
# macOS (even for a .wav path); soundfile reads both, giving portable PCM.
data, samplerate = sf.read(_SCRATCH_WAV, dtype="int16")
# sounddevice (PortAudio) plays it and blocks on sd.wait() — reliable and
# OS-agnostic. (simpleaudio segfaults on Apple Silicon / Python 3.12.)
print("speaking")
sd.play(data, samplerate)
sd.wait()
print("done")

