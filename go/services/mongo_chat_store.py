"""
MongoDB Chat Store — Persistent conversation storage for the AI chatbot.
=========================================================================
Replaces SQLiteSession with MongoDB-backed storage.
Implements the same SessionABC interface that OpenAI Agents SDK expects.

Collections:
  - chat_sessions: {session_id, created_at, updated_at}
  - chat_messages: {session_id, message_data (JSON), seq (auto-inc), created_at}

Why MongoDB instead of SQLite:
  - Persistent across server restarts (SQLite file could get wiped)
  - Shared across multiple server instances
  - Better for production — proper database with backup/restore
  - Chat data is document-shaped (JSON messages) — natural fit for MongoDB
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ─── MongoDB Connection (lazy singleton) ─────────────────────
_mongo_client: Optional[AsyncIOMotorClient] = None
_mongo_db: Optional[AsyncIOMotorDatabase] = None


def _get_db() -> AsyncIOMotorDatabase:
    """Get or create the MongoDB database connection."""
    global _mongo_client, _mongo_db
    if _mongo_db is None:
        _mongo_client = AsyncIOMotorClient(settings.MONGODB_URL)
        _mongo_db = _mongo_client[settings.MONGODB_DATABASE]
        logger.info(f"[MongoDB] Connected to {settings.MONGODB_URL}/{settings.MONGODB_DATABASE}")
    return _mongo_db


async def ensure_indexes():
    """Create indexes for efficient queries. Safe to call multiple times."""
    db = _get_db()
    await db.chat_messages.create_index([("session_id", 1), ("seq", 1)])
    await db.chat_messages.create_index([("session_id", 1), ("created_at", 1)])
    await db.chat_sessions.create_index("session_id", unique=True)
    logger.info("[MongoDB] Chat indexes ensured")


async def close_mongo():
    """Close the MongoDB connection (call on shutdown)."""
    global _mongo_client, _mongo_db
    if _mongo_client:
        _mongo_client.close()
        _mongo_client = None
        _mongo_db = None
        logger.info("[MongoDB] Connection closed")


# ─── MongoSession — implements SessionABC interface ───────────

class MongoSession:
    """MongoDB-backed session that implements the OpenAI Agents SDK Session interface.

    Drop-in replacement for SQLiteSession. Used by OpenAIResponsesCompactionSession
    as the underlying_session.

    Interface methods:
      - get_items(limit) → list of message dicts
      - add_items(items) → store new messages
      - pop_item() → remove and return the latest message
      - clear_session() → delete all messages for this session
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.session_settings = None  # Will use defaults

    async def _ensure_session(self):
        """Create session record if it doesn't exist."""
        db = _get_db()
        now = datetime.now(timezone.utc)
        await db.chat_sessions.update_one(
            {"session_id": self.session_id},
            {"$setOnInsert": {"created_at": now}, "$set": {"updated_at": now}},
            upsert=True,
        )

    async def _next_seq(self) -> int:
        """Get the next sequence number for this session's messages."""
        db = _get_db()
        last = await db.chat_messages.find_one(
            {"session_id": self.session_id},
            sort=[("seq", -1)],
            projection={"seq": 1},
        )
        return (last["seq"] + 1) if last else 1

    async def get_items(self, limit: Optional[int] = None) -> list:
        """Retrieve conversation history for this session.

        Args:
            limit: Max items to return (latest N in chronological order).
                   None = all items.
        """
        db = _get_db()

        if limit is None:
            # All items in chronological order
            cursor = db.chat_messages.find(
                {"session_id": self.session_id},
                projection={"_id": 0, "message_data": 1},
            ).sort("seq", 1)
        else:
            # Latest N items: find total, skip to get last N, in chrono order
            total = await db.chat_messages.count_documents({"session_id": self.session_id})
            skip = max(0, total - limit)
            cursor = db.chat_messages.find(
                {"session_id": self.session_id},
                projection={"_id": 0, "message_data": 1},
            ).sort("seq", 1).skip(skip)

        items = []
        async for doc in cursor:
            raw = doc["message_data"]
            if isinstance(raw, str):
                items.append(json.loads(raw))
            else:
                items.append(raw)
        return items

    async def add_items(self, items: list) -> None:
        """Add new items to conversation history."""
        if not items:
            return

        await self._ensure_session()
        db = _get_db()
        seq = await self._next_seq()
        now = datetime.now(timezone.utc)

        docs = []
        for item in items:
            docs.append({
                "session_id": self.session_id,
                "seq": seq,
                "message_data": json.dumps(item) if not isinstance(item, str) else item,
                "created_at": now,
            })
            seq += 1

        if docs:
            await db.chat_messages.insert_many(docs)

    async def pop_item(self) -> Optional[dict]:
        """Remove and return the most recent item."""
        db = _get_db()

        # Find the latest message
        last = await db.chat_messages.find_one(
            {"session_id": self.session_id},
            sort=[("seq", -1)],
        )
        if not last:
            return None

        # Delete it
        await db.chat_messages.delete_one({"_id": last["_id"]})

        raw = last["message_data"]
        if isinstance(raw, str):
            return json.loads(raw)
        return raw

    async def clear_session(self) -> None:
        """Delete all messages and the session record."""
        db = _get_db()
        await db.chat_messages.delete_many({"session_id": self.session_id})
        await db.chat_sessions.delete_one({"session_id": self.session_id})
        logger.info(f"[MongoDB] Cleared session {self.session_id}")


# ─── History retrieval (for /chat/history endpoint) ──────────

async def get_conversation_history_mongo(user_id: str, limit: int = 100) -> list[dict]:
    """Retrieve stored conversation history for a user from MongoDB.

    Returns a list of {role: 'user'|'assistant', content: str} dicts
    suitable for displaying in the Streamlit chat UI.
    Strips [MANDATORY:...] and [SYSTEM REMINDER:...] prefixes from user messages.
    """
    import re

    try:
        session = MongoSession(session_id=user_id)
        items = await session.get_items(limit=limit)
        messages = []

        for item in items:
            # Handle both dict and JSON string
            if isinstance(item, str):
                try:
                    item = json.loads(item)
                except json.JSONDecodeError:
                    continue

            role = item.get("role", "")
            content_parts = item.get("content", [])

            # Extract text from content parts
            text = ""
            if isinstance(content_parts, str):
                text = content_parts
            elif isinstance(content_parts, list):
                for part in content_parts:
                    if isinstance(part, dict):
                        if part.get("type") in ("input_text", "output_text", "text"):
                            text += part.get("text", "")
                    elif isinstance(part, str):
                        text += part

            if text and role in ("user", "assistant"):
                # Strip injected system reminders from user messages
                if role == "user":
                    text = re.sub(r'\[MANDATORY:.*?\]\n*', '', text, flags=re.DOTALL).strip()
                    text = re.sub(r'\[SYSTEM REMINDER:.*?\]\n*', '', text, flags=re.DOTALL).strip()
                    # Also strip [Form Context]...[User Message] wrapper
                    form_match = re.search(r'\[User Message\]\s*(.*)', text, flags=re.DOTALL)
                    if form_match:
                        text = form_match.group(1).strip()
                if text:
                    messages.append({"role": role, "content": text})

        return messages
    except Exception as e:
        logger.warning(f"[MongoDB] Could not retrieve history for {user_id}: {e}")
        return []
