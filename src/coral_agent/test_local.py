"""
Local test script for CORAL dialogue agent.

Tests the LLM dialogue logic without requiring Daily or audio.
"""

import os

from dotenv import load_dotenv
from loguru import logger
from openai import OpenAI

load_dotenv()

SYSTEM_PROMPT = """You are a friendly robot teaching assistant helping children program robot movements.

Your job is to:
1. Listen to the child's instruction about how the robot should move
2. Extract these control parameters if mentioned:
   - target_joint: which part of the robot to move (e.g., "arm", "head", "left leg")
   - direction: which way to move (e.g., "up", "down", "left", "right", "forward")
   - angle: how far to rotate in degrees (e.g., "45 degrees", "a little bit")
   - speed: how fast to move (e.g., "slowly", "fast", "medium")

3. If any parameters are missing or unclear, ask a simple clarification question
4. When you have enough information, confirm the command back to the child

Keep your responses short, friendly, and age-appropriate for children (ages 8-12).

When you have a complete command, output it in this format at the end of your response:
[COMMAND: joint=<joint>, direction=<direction>, angle=<angle>, speed=<speed>]
"""


def test_dialogue():
    """Test the dialogue system with text input."""

    model = "gpt-4o-mini"
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    logger.info("CORAL Dialogue Test")
    logger.info(f"Using model: {model}")
    logger.info("Type a robot instruction (or 'quit' to exit)")
    logger.info("-" * 50)

    while True:
        try:
            user_input = input("\nYou: ").strip()
            if user_input.lower() in ("quit", "exit", "q"):
                break
            if not user_input:
                continue

            messages.append({"role": "user", "content": user_input})

            response = client.chat.completions.create(model=model, messages=messages)

            assistant_message = response.choices[0].message.content
            messages.append({"role": "assistant", "content": assistant_message})

            print(f"\nAssistant: {assistant_message}")

        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Error: {e}")

    logger.info("Goodbye!")


if __name__ == "__main__":
    test_dialogue()
