"""Agent builder and public API for the chat service.

Constructs role-specific agents with appropriate tools and instructions,
and provides the main run_chat() entry point for client code.
"""

import logging
import os
from datetime import date

from agents import Agent, Runner

from config import get_settings

from go.services.chat._client import _clear_proxy_env
from go.services.chat.prompts import ROLE_CONFIG, MODEL
from go.services.chat.memory import _get_session

logger = logging.getLogger(__name__)
settings = get_settings()


def _build_agent(role: str) -> Agent:
    """Build one agent for the given role with the right tools and instructions."""
    today_str = date.today().isoformat()
    config = ROLE_CONFIG.get(role, ROLE_CONFIG["patient"])

    # The "always re-fetch" reminder lives in the system prompt (not per-message)
    # so it doesn't waste tokens on every single user message.
    instructions = (
        f"Today: {today_str}. User role: {role.upper()}.\n\n"
        "DATA FRESHNESS: When the user asks about sessions, queue, appointments, or patients, "
        "ALWAYS call tools to get current data. Never reuse stale data from earlier messages.\n"
        "CASUAL MESSAGES: For greetings (hi, hello), thanks, or small talk — just reply naturally. "
        "Do NOT call tools or continue previous tasks.\n\n"
        f"{config['instructions']}"
    )

    return Agent(
        name=f"DPMS_{role.title()}_Assistant",
        instructions=instructions,
        tools=config["tools"],
        model=MODEL,
    )


async def run_chat(
    message: str,
    token: str,
    role: str,
    user_id: str = "",
    patient_id: str = "",
    doctor_id: str = "",
    patient_context: str = "",
) -> str:
    """Run the chatbot agent with a user message and return the reply.

    Uses MongoDB + compaction for efficient conversation memory.
    The SDK handles context trimming/summarization automatically —
    old messages get compressed, recent ones stay verbatim.
    Client only sends the new message. No history needed.
    """
    if not settings.OPENAI_API_KEY:
        return ("The AI chatbot is not configured. Please set OPENAI_API_KEY "
                "in the .env file and restart the server.")

    os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
    _clear_proxy_env()

    context = {"token": token, "role": role, "patient_id": patient_id, "doctor_id": doctor_id}
    agent = _build_agent(role)
    session = _get_session(user_id)

    # Build user input — inject form context on first message only
    user_input = message
    if patient_context:
        try:
            if not await session.get_items():
                user_input = f"[Form Context]\n{patient_context}\n\n[User Message]\n{message}"
        except Exception:
            user_input = f"[Form Context]\n{patient_context}\n\n[User Message]\n{message}"

    try:
        result = await Runner.run(
            agent,
            input=user_input,
            context=context,
            session=session,
        )
        return result.final_output
    except Exception as e:
        logger.error(f"Chat agent error: {e}", exc_info=True)
        return f"I'm sorry, I encountered an error. Please try again. ({type(e).__name__}: {e})"
