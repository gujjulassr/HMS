"""Session-based conversation memory backed by MongoDB.

Handles persistent storage and compaction of chat histories per user.
Each user gets their own OpenAIResponsesCompactionSession that automatically
summarizes older messages to keep context efficient.

Separate UI history (simple role+content pairs) is stored alongside
the SDK session so the frontend always gets clean, recent messages.
"""

import logging
import time

from agents.memory import OpenAIResponsesCompactionSession

from go.services.mongo_chat_store import (
    MongoSession,
    save_ui_message,
    get_ui_history,
    clear_ui_history,
)

logger = logging.getLogger(__name__)

# Track active sessions per user: user_id -> (compaction session, last_access_time)
_active_sessions: dict[str, tuple[OpenAIResponsesCompactionSession, float]] = {}
_MAX_CACHED_SESSIONS = 200  # evict oldest when we exceed this


def _evict_old_sessions():
    """Remove least-recently-used sessions when cache is too large."""
    if len(_active_sessions) <= _MAX_CACHED_SESSIONS:
        return
    # Sort by last access time, remove oldest half
    sorted_keys = sorted(_active_sessions, key=lambda k: _active_sessions[k][1])
    to_remove = sorted_keys[:len(sorted_keys) // 2]
    for k in to_remove:
        del _active_sessions[k]
    logger.info(f"Evicted {len(to_remove)} idle chat sessions (had {len(sorted_keys)})")


def _get_session(user_id: str) -> OpenAIResponsesCompactionSession:
    """Get or create a compacted session for a user (MongoDB-backed)."""
    if user_id in _active_sessions:
        session, _ = _active_sessions[user_id]
        _active_sessions[user_id] = (session, time.time())
        return session

    _evict_old_sessions()

    underlying = MongoSession(session_id=user_id)
    session = OpenAIResponsesCompactionSession(
        session_id=user_id,
        underlying_session=underlying,
    )
    _active_sessions[user_id] = (session, time.time())
    return session


async def clear_conversation(user_id: str) -> None:
    """Clear a user's conversation — both SDK session and UI history."""
    _active_sessions.pop(user_id, None)
    # Clear SDK session from MongoDB
    try:
        underlying = MongoSession(session_id=user_id)
        await underlying.clear_session()
    except Exception as e:
        logger.warning(f"Could not clear SDK session for {user_id}: {e}")
    # Clear UI history
    try:
        await clear_ui_history(user_id)
    except Exception as e:
        logger.warning(f"Could not clear UI history for {user_id}: {e}")


async def get_conversation_history(user_id: str, limit: int = 50) -> list[dict]:
    """Retrieve clean UI-friendly conversation history."""
    return await get_ui_history(user_id, limit=limit)


async def save_message(user_id: str, role: str, content: str) -> None:
    """Save a single message to UI history."""
    await save_ui_message(user_id, role, content)
