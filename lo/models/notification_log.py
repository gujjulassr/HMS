"""
LO Model: notification_log
Tracks every notification sent through any adapter (email, SMS).
"""
from uuid import UUID
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class NotificationLog:
    id: UUID
    user_id: UUID
    appointment_id: Optional[UUID]
    type: str
    channel: str
    status: str
    content: str
    error_message: Optional[str]
    sent_at: Optional[datetime]
    created_at: datetime


class NotificationModel:

    @staticmethod
    async def create(
        db: AsyncSession,
        user_id: UUID,
        type: str,
        channel: str,
        content: str,
        appointment_id: Optional[UUID] = None,
    ) -> NotificationLog:
        result = await db.execute(
            text("""
                INSERT INTO notification_log
                    (user_id, appointment_id, type, channel, content)
                VALUES
                    (:user_id, :appt_id, :type, :channel, :content)
                RETURNING *
            """),
            {
                "user_id": user_id,
                "appt_id": appointment_id,
                "type": type,
                "channel": channel,
                "content": content,
            },
        )
        row = result.mappings().one()
        await db.commit()  # Persist changes to database
        return NotificationLog(**row)

    @staticmethod
    async def update_status(
        db: AsyncSession,
        log_id: UUID,
        status: str,
        error_message: Optional[str] = None,
    ) -> bool:
        if status == "sent":
            result = await db.execute(
                text("""
                    UPDATE notification_log
                    SET status = 'sent', sent_at = NOW()
                    WHERE id = :id
                """),
                {"id": log_id},
            )
        else:
            result = await db.execute(
                text("""
                    UPDATE notification_log
                    SET status = :status, error_message = :error
                    WHERE id = :id
                """),
                {"id": log_id, "status": status, "error": error_message},
            )
        await db.commit()  # Persist changes to database
        return result.rowcount > 0

    @staticmethod
    async def get_pending(db: AsyncSession, limit: int = 50) -> List[NotificationLog]:
        result = await db.execute(
            text("""
                SELECT * FROM notification_log
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT :limit
            """),
            {"limit": limit},
        )
        return [NotificationLog(**row) for row in result.mappings().all()]

    @staticmethod
    async def get_by_user(
        db: AsyncSession, user_id: UUID, limit: int = 20
    ) -> List[NotificationLog]:
        result = await db.execute(
            text("""
                SELECT * FROM notification_log
                WHERE user_id = :uid
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            {"uid": user_id, "limit": limit},
        )
        return [NotificationLog(**row) for row in result.mappings().all()]
