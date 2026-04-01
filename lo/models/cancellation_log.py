"""
LO Model: cancellation_log
Immutable record of every cancellation.
Stores the risk_delta that was added to the booker's risk_score.
"""
from uuid import UUID
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List
from decimal import Decimal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class CancellationLog:
    id: UUID
    appointment_id: UUID
    cancelled_by_patient_id: UUID
    reason: Optional[str]
    risk_delta: Decimal
    hours_before_appointment: Decimal
    created_at: datetime


class CancellationModel:

    @staticmethod
    async def create(
        db: AsyncSession,
        appointment_id: UUID,
        cancelled_by_patient_id: UUID,
        risk_delta: Decimal,
        hours_before_appointment: Decimal,
        reason: Optional[str] = None,
    ) -> CancellationLog:
        result = await db.execute(
            text("""
                INSERT INTO cancellation_log
                    (appointment_id, cancelled_by_patient_id, risk_delta,
                     hours_before_appointment, reason)
                VALUES
                    (:appt_id, :cancelled_by, :delta, :hours_before, :reason)
                RETURNING *
            """),
            {
                "appt_id": appointment_id,
                "cancelled_by": cancelled_by_patient_id,
                "delta": risk_delta,
                "hours_before": hours_before_appointment,
                "reason": reason,
            },
        )
        row = result.mappings().one()
        return CancellationLog(**row)

    @staticmethod
    async def get_last_cancel_time(
        db: AsyncSession, patient_id: UUID
    ) -> Optional[datetime]:
        """Get the most recent cancellation time for cooldown check."""
        result = await db.execute(
            text("""
                SELECT MAX(created_at) FROM cancellation_log
                WHERE cancelled_by_patient_id = :pid
            """),
            {"pid": patient_id},
        )
        return result.scalar()

    @staticmethod
    async def get_by_patient(
        db: AsyncSession, patient_id: UUID, limit: int = 20
    ) -> List[CancellationLog]:
        result = await db.execute(
            text("""
                SELECT * FROM cancellation_log
                WHERE cancelled_by_patient_id = :pid
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            {"pid": patient_id, "limit": limit},
        )
        return [CancellationLog(**row) for row in result.mappings().all()]

    @staticmethod
    async def get_by_appointment(
        db: AsyncSession, appointment_id: UUID
    ) -> Optional[CancellationLog]:
        result = await db.execute(
            text("SELECT * FROM cancellation_log WHERE appointment_id = :appt_id"),
            {"appt_id": appointment_id},
        )
        row = result.mappings().first()
        return CancellationLog(**row) if row else None
