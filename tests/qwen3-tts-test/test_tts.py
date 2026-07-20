import time
import torch
import sounddevice as sd
from qwen_tts import Qwen3TTSModel

MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
INSTRUCT = "You are a humanoid robot that is speaking to a very young child, you are like a teacher, have a friendly tone"

COMMANDS = """
Commands:
  /speakers          - list available speakers
  /speaker <name>    - switch speaker
  /instruct <text>   - set voice instruction (e.g. "speak in an excited tone")
  /instruct clear    - remove current instruction
  /quit              - exit
"""


def load_model():
    print(f"Loading {MODEL_ID} on GPU...")
    kwargs = dict(
        device_map="cuda:0",
        dtype=torch.bfloat16,
    )
    try:
        import flash_attn  # noqa: F401

        kwargs["attn_implementation"] = "flash_attention_2"
        print("Using FlashAttention 2")
    except ImportError:
        print("FlashAttention 2 not found, using default attention")

    model = Qwen3TTSModel.from_pretrained(MODEL_ID, **kwargs)
    return model


def main():
    model = load_model()

    speakers = model.get_supported_speakers() or ["default"]
    speaker = speakers[0]
    instruct = INSTRUCT

    print(f"\nAvailable speakers: {speakers}")
    print(f"Speaker: {speaker} | Instruction: {instruct or 'none'}")
    print(COMMANDS)

    while True:
        try:
            line = input("Enter text: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break

        if not line:
            continue

        if line == "/quit":
            print("Exiting.")
            break
        elif line == "/speakers":
            print(f"Available speakers: {speakers}")
            continue
        elif line.startswith("/speaker "):
            name = line[len("/speaker ") :].strip()
            if name in speakers:
                speaker = name
                print(f"Speaker set to: {speaker}")
            else:
                print(f"Unknown speaker '{name}'. Available: {speakers}")
            continue
        elif line.startswith("/instruct "):
            value = line[len("/instruct ") :].strip()
            if value == "clear":
                instruct = None
                print("Instruction cleared.")
            else:
                instruct = value
                print(f"Instruction set to: {instruct}")
            continue

        print(f"[Speaker: {speaker} | Instruction: {instruct or 'none'}]")
        t_start = time.perf_counter()

        wavs, sr = model.generate_custom_voice(
            text=line,
            speaker=speaker,
            language="English",
            instruct=instruct,
        )

        t_end = time.perf_counter()
        print(f"Processing time: {t_end - t_start:.3f}s")

        audio = wavs[0]
        print(f"Playing audio ({len(audio) / sr:.2f}s)...")
        sd.play(audio, sr)
        sd.wait()


if __name__ == "__main__":
    main()
