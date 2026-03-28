"""
CORAL Voice AI Dialogue Agent

A voice-based agent that helps translate children's spoken instructions
into executable robot commands through clarification dialogues.
"""

import asyncio
import os

from dotenv import load_dotenv
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.ollama.llm import OLLamaLLMService
from pipecat.transports.daily.transport import DailyParams, DailyTransport

load_dotenv()

# System prompt for the CORAL dialogue agent
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

Example interaction:
Child: "Make the arm go up"
You: "Got it! How far should the arm go up? A little bit, halfway, or all the way?"
Child: "Halfway"
You: "Perfect! I'll move the arm up halfway at medium speed. Here we go!"

When you have a complete command, output it in this format at the end of your response:
[COMMAND: joint=<joint>, direction=<direction>, angle=<angle>, speed=<speed>]
"""


async def main():
    """Main entry point for the CORAL dialogue agent."""

    daily_api_key = os.getenv("DAILY_API_KEY")
    if not daily_api_key:
        logger.error("DAILY_API_KEY environment variable is required")
        return

    # Configure Daily transport for real-time audio
    transport = DailyTransport(
        room_url=os.getenv("DAILY_ROOM_URL", ""),
        token=None,
        bot_name="CORAL Assistant",
        params=DailyParams(
            api_key=daily_api_key,
            audio_in_enabled=True,
            audio_out_enabled=False,  # Text output only for now
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )

    # Configure Ollama LLM service
    ollama_service = OLLamaLLMService(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        model=os.getenv("OLLAMA_MODEL", "llama3.2"),
    )

    # Set up conversation context
    context = OpenAILLMContext(
        messages=[{"role": "system", "content": SYSTEM_PROMPT}]
    )
    context_aggregator = ollama_service.create_context_aggregator(context)

    # Build the pipeline
    pipeline = Pipeline(
        [
            transport.input(),
            context_aggregator.user(),
            ollama_service,
            context_aggregator.assistant(),
            transport.output(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
        ),
    )

    @transport.event_handler("on_participant_joined")
    async def on_participant_joined(transport, participant):
        logger.info(f"Participant joined: {participant['id']}")

    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant, reason):
        logger.info(f"Participant left: {participant['id']}, reason: {reason}")

    runner = PipelineRunner()

    logger.info("Starting CORAL Voice AI Agent...")
    await runner.run(task)


def run():
    """Entry point for the bot-test command."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
