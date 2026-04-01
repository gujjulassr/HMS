"""
LO Model: waitlist
When all slot positions are taken, patient goes here.
Auto-promoted when a cancellation frees a spot.
"""
from uuid import UUID
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class WaitlistEntry:
    id: UUID
    session_id: UUID
    patient_id: UUID
    booked_by_patient_id: UUID
    priority_tier: str
    status: str
    promoted_at: Optional[datetime]
    created_at: datetime


class WaitlistModel:

    @staticmethod
    async def create(
        db: AsyncSession,
        session_id: UUID,
        patient_id: UUID,
        booked_by_patient_id: UUID,
        priority_tier: str,
    ) -> WaitlistEntry:
        result = await db.execute(
            text("""
                INSERT INTO waitlist
                    (session_id, patient_id, booked_by_patient_id, priority_tier)
                VALUES
                    (:session_id, :patient_id, :booked_by, :priority)
                RETURNING *
            """),
            {
                "session_id": session_id,
                "patient_id": patient_id,
                "booked_by": booked_by_patient_id,
                "priority": priority_tier,
            },
        )
        row = result.mappings().one()
        return WaitlistEntry(**row)

    @staticmethod
    async def get_next_waiting(
        db: AsyncSession, session_id: UUID
    ) -> Optional[WaitlistEntry]:
        """Get next patient to promote. Ordered by priority_tier DESC, created_at ASC."""
        result = await db.execute(
            text("""
                SELECT * FROM waitlist
                WHERE session_id = :session_id
                  AND status = 'waiting'
                ORDER BY
                    CASE priority_tier
                        WHEN 'CRITICAL' THEN 3
                        WHEN 'HIGH' THEN 2
                        WHEN 'NORMAL' THEN 1
                    END DESC,
                    created_at ASC
                LIMIT 1
            """),
            {"session_id": session_id},
        )
        row = result.mappings().first()
        return WaitlistEntry(**row) if row else None

    @staticmethod
    async def promote(db: AsyncSession, waitlist_id: UUID) -> Optional[WaitlistEntry]:
        result = await db.execute(
            text("""
                UPDATE waitlist
                SET status = 'promoted', promoted_at = NOW()
                WHERE id = :id AND status = 'waiting'
                RETURNING *
            """),
            {"id": waitlist_id},
        )
        row = result.mappings().first()
        return WaitlistEntry(**row) if row else None

    @staticmethod
    async def cancel(db: AsyncSession, waitlist_id: UUID) -> bool:
        result = await db.execute(
            text("UPDATE waitlist SET status = 'cancelled' WHERE id = :id AND status = 'waiting'"),
            {"id": waitlist_id},
        )
        return result.rowcount > 0

    @staticmethod
    async def get_by_session(db: AsyncSession, session_id: UUID) -> List[WaitlistEntry]:
        result = await db.execute(
            text("""
                SELECT * FROM waitlist
                WHERE session_id = :session_id
                ORDER BY status, created_at
            """),
            {"session_id": session_id},
        )
        return [WaitlistEntry(**row) for row in result.mappings().all()]

    @staticmethod
    async def expire_old_entries(db: AsyncSession) -> int:
        """Nightly job: expire waitlist entries for past sessions."""
        result = await db.execute(
            text("""
                UPDATE waitlist w
                SET status = 'expired'
                FROM sessions s
                WHERE w.session_id = s.id
                  AND w.status = 'waiting'
                  AND s.session_date < CURRENT_DATE
            """)
        )
        return result.rowcount
