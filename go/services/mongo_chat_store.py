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
    await db.chat_sessions.create_index([("session_id", 1)], unique=True)
    await db.chat_ui_history.create_index([("user_id", 1), ("created_at", 1)])
    await db.chat_seq_counters.create_index([("session_id", 1)], unique=True)
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

    async def _next_seq(self, count: int = 1) -> int:
        """Atomically reserve the next `count` sequence numbers for this session."""
        db = _get_db()
        result = await db.chat_seq_counters.find_one_and_update(
            {"session_id": self.session_id},
            {"$inc": {"seq": count}},
            upsert=True,
            return_document=True,
        )
        # Returns the AFTER value, so first reserved seq = result - count + 1
        return result["seq"] - count + 1

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
        seq = await self._next_seq(count=len(items))
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
        """Atomically remove and return the most recent item."""
        db = _get_db()

        last = await db.chat_messages.find_one_and_delete(
            {"session_id": self.session_id},
            sort=[("seq", -1)],
        )
        if not last:
            return None

        raw = last["message_data"]
        if isinstance(raw, str):
            return json.loads(raw)
        return raw

    async def clear_session(self) -> None:
        """Delete all messages, seq counter, and the session record."""
        db = _get_db()
        await db.chat_messages.delete_many({"session_id": self.session_id})
        await db.chat_seq_counters.delete_one({"session_id": self.session_id})
        await db.chat_sessions.delete_one({"session_id": self.session_id})
        logger.info(f"[MongoDB] Cleared session {self.session_id}")


# ─── UI Chat History (separate from SDK session) ──────────────
#
# The SDK session stores complex response objects that get compacted/summarized.
# Parsing those back into clean {role, content} is unreliable — compaction
# fragments old messages, tool-call items pollute the list, etc.
#
# Instead, we keep a simple parallel collection `chat_ui_history` that stores
# exactly what the user sees: {user_id, role, content, created_at}.
# This is written by the chat API on every send/receive and read on page load.

async def save_ui_message(user_id: str, role: str, content: str) -> None:
    """Append one message to the UI history (call for both user + assistant)."""
    db = _get_db()
    await db.chat_ui_history.insert_one({
        "user_id": user_id,
        "role": role,
        "content": content,
        "created_at": datetime.now(timezone.utc),
    })


async def get_ui_history(user_id: str, limit: int = 50) -> list[dict]:
    """Retrieve clean UI-friendly messages (most recent `limit`)."""
    db = _get_db()
    total = await db.chat_ui_history.count_documents({"user_id": user_id})
    skip = max(0, total - limit)
    cursor = db.chat_ui_history.find(
        {"user_id": user_id},
        projection={"_id": 0, "role": 1, "content": 1},
    ).sort("created_at", 1).skip(skip)
    return [doc async for doc in cursor]


async def clear_ui_history(user_id: str) -> None:
    """Wipe the UI history for a user (called on New Chat / Clear Chat)."""
    db = _get_db()
    await db.chat_ui_history.delete_many({"user_id": user_id})
