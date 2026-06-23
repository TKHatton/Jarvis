"""
Jarvis Agent — Updated to use local JarvisMemory instead of Mem0.

Changes from original:
  - Replaced: from mem0 import AsyncMemoryClient → from jarvis_memory import JarvisMemory
  - Memory client is now local (SQLite file), no subscription cost
  - Same search/add interface — minimal code changes
  - Added: JARVIS_EMBED_LOCAL=1 env var option for free local embeddings
"""

from dotenv import load_dotenv

from livekit import agents
from livekit.agents import AgentSession, Agent, RoomInputOptions, ChatContext
from livekit.plugins import noise_cancellation, google

from prompts import AGENT_INSTRUCTION, SESSION_INSTRUCTION
from tools import (
    # Core tools
    get_weather, search_web,
    # File tools
    create_file, read_file, list_files,
    # Memory tools
    remember_this, recall, memory_stats,
    # Gmail tools
    check_email, search_email, draft_email, send_email,
    # Calendar tools
    check_schedule, create_event, check_conflicts,
    # Drive tools
    upload_to_drive, search_drive, read_drive_file,
    # Code tools
    run_python, save_script,
    # Course generation tools
    generate_course_outline, generate_lesson, generate_workbook,
    # Image generation tools
    generate_image,
)
from jarvis_memory import JarvisMemory  # ← CHANGED: was `from mem0 import AsyncMemoryClient`
import json
import logging

load_dotenv(".env")


class Assistant(Agent):
    def __init__(self, chat_ctx=None) -> None:
        super().__init__(
            instructions=AGENT_INSTRUCTION,

            llm=google.beta.realtime.RealtimeModel(
                model="gemini-2.5-flash-native-audio-preview-12-2025",
                voice="Charon",
                temperature=0.8,
            ),

            tools=[
                # Core
                get_weather, search_web,
                # Files
                create_file, read_file, list_files,
                # Memory
                remember_this, recall, memory_stats,
                # Gmail
                check_email, search_email, draft_email, send_email,
                # Calendar
                check_schedule, create_event, check_conflicts,
                # Drive
                upload_to_drive, search_drive, read_drive_file,
                # Code
                run_python, save_script,
                # Course generation
                generate_course_outline, generate_lesson, generate_workbook,
                # Image generation
                generate_image,
            ],
            chat_ctx=chat_ctx

        )

async def entrypoint(ctx: agents.JobContext):
    # ← CHANGED: local memory instead of Mem0
    memory = JarvisMemory()  # creates jarvis_memory.db in current directory
    user_name = "Ma'am"

    # Connect to the room first
    await ctx.connect()

    # Retrieve memories for the user
    results = []
    try:
        results = await memory.search(
            query=f"Everything about {user_name}",
            filters={"user_id": user_name}
        )
        # ← CHANGED: results are already a list of dicts, no need to unwrap
    except Exception as e:
        logging.warning(f"Could not retrieve memories: {e}")
        results = []

    initial_ctx = ChatContext()
    memory_str = ''

    if results:
        memories = []
        for result in results:
            memories.append({
                "memory": result.get("memory", str(result)),
                "updated_at": result.get("updated_at", "")
            })

        memory_str = json.dumps(memories)
        logging.info(f"Memories: {memory_str}")

        initial_ctx.add_message(
            role="assistant",
            content=f"The user's name is {user_name}, and this is relevant context about her: {memory_str}."
        )

    async def save_memories_on_shutdown():
        """Save chat context to memory when the session ends."""
        logging.info("Shutting down, saving chat context to memory...")

        messages_formatted = []
        chat_ctx = session._chat_ctx

        logging.info(f"Chat context messages: {chat_ctx.items}")

        for item in chat_ctx.items:
            # Skip items that aren't ChatMessage (e.g., AgentHandoff)
            if not hasattr(item, 'content') or not hasattr(item, 'role'):
                continue

            content_str = (
                "".join(item.content)
                if isinstance(item.content, list)
                else str(item.content)
            )

            # Skip the memory context message we injected
            if memory_str and memory_str in content_str:
                continue

            if item.role in ["user", "assistant"]:
                messages_formatted.append({
                    "role": item.role,
                    "content": content_str.strip()
                })

        logging.info(f"Formatted messages to add to memory: {messages_formatted}")

        if messages_formatted:
            try:
                # ← CHANGED: same .add() interface, just local now
                await memory.add(messages_formatted, user_id=user_name)
                logging.info("Chat context saved to memory.")
            except Exception as e:
                logging.error(f"Failed to save memory: {e}")

    session = AgentSession(
        # Turn detection is handled by the RealtimeModel internally
    )

    # Register shutdown callback BEFORE starting the session
    ctx.add_shutdown_callback(save_memories_on_shutdown)

    # Start the session
    await session.start(
        room=ctx.room,
        agent=Assistant(chat_ctx=initial_ctx),
        room_input_options=RoomInputOptions(
            video_enabled=True,
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )

    # Generate initial greeting
    session.generate_reply(
        instructions=SESSION_INSTRUCTION,
    )


if __name__ == "__main__":
    agents.cli.run_app(
        agents.WorkerOptions(
            entrypoint_fnc=entrypoint,
        )
    )