"""
LO Model: appointments
Core transaction table. Created per booking.
Lifecycle: booked → checked_in → in_progress → completed
"""
from uuid import UUID
from datetime import datetime, date
from dataclasses import dataclass
from typing import Optional, List
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class Appointment:
    id: UUID
    session_id: UUID
    patient_id: UUID              # Beneficiary
    booked_by_patient_id: UUID    # Booker
    slot_number: int
    slot_position: int            # 1 = original, 2 = overbook, 3 = emergency
    priority_tier: str            # NORMAL, HIGH, CRITICAL (immutable)
    visual_priority: int          # 1-10, nurse sets at check-in
    is_emergency: bool            # Emergency override by admin/staff
    status: str
    checked_in_at: Optional[datetime]
    checked_in_by: Optional[UUID]
    completed_at: Optional[datetime]
    notes: Optional[str]
    duration_minutes: Optional[int] = None  # Nurse override; NULL = session default
    created_at: datetime = None
    updated_at: datetime = None


def _safe_appointment(row) -> 'Appointment':
    """Build Appointment from a DB row, handling missing optional columns."""
    d = dict(row)
    # duration_minutes might not exist if migration 016 hasn't run
    if 'duration_minutes' not in d:
        d['duration_minutes'] = None
    return Appointment(**d)


class AppointmentModel:

    @staticmethod
    async def create(
        db: AsyncSession,
        session_id: UUID,
        patient_id: UUID,
        booked_by_patient_id: UUID,
        slot_number: int,
        slot_position: int,
        priority_tier: str,
        is_emergency: bool = False,
        visual_priority: int = 5,
    ) -> Appointment:
        result = await db.execute(
            text("""
                INSERT INTO appointments
                    (session_id, patient_id, booked_by_patient_id,
                     slot_number, slot_position, priority_tier, is_emergency, visual_priority)
                VALUES
                    (:session_id, :patient_id, :booked_by,
                     :slot_num, :slot_pos, :priority, :is_emergency, :visual_priority)
                RETURNING *
            """),
            {
                "session_id": session_id,
                "patient_id": patient_id,
                "booked_by": booked_by_patient_id,
                "slot_num": slot_number,
                "slot_pos": slot_position,
                "priority": priority_tier,
                "is_emergency": is_emergency,
                "visual_priority": visual_priority,
            },
        )
        row = result.mappings().one()
        return _safe_appointment(row)

    @staticmethod
    async def get_by_id(db: AsyncSession, appt_id: UUID) -> Optional[Appointment]:
        result = await db.execute(
            text("SELECT * FROM appointments WHERE id = :id"),
            {"id": appt_id},
        )
        row = result.mappings().first()
        return _safe_appointment(row) if row else None

    @staticmethod
    async def count_by_session_slot(
        db: AsyncSession, session_id: UUID, slot_number: int
    ) -> int:
        """Count booked (non-cancelled) appointments for a specific slot."""
        result = await db.execute(
            text("""
                SELECT COUNT(*) as cnt FROM appointments
                WHERE session_id = :session_id
                  AND slot_number = :slot_num
                  AND status != 'cancelled'
            """),
            {"session_id": session_id, "slot_num": slot_number},
        )
        return result.scalar()

    @staticmethod
    async def get_next_slot_position(
        db: AsyncSession, session_id: UUID, slot_number: int, is_emergency: bool = False
    ) -> Optional[int]:
        """
        Get next available slot_position.
        Normal booking: 1 or 2. Returns None if full.
        Emergency: 1, 2, or 3. Position 3 = emergency override (always available).
        """
        result = await db.execute(
            text("""
                SELECT slot_position FROM appointments
                WHERE session_id = :session_id
                  AND slot_number = :slot_num
                  AND status != 'cancelled'
                ORDER BY slot_position
            """),
            {"session_id": session_id, "slot_num": slot_number},
        )
        taken = [row[0] for row in result.all()]
        if 1 not in taken:
            return 1
        if 2 not in taken:
            return 2
        if is_emergency and 3 not in taken:
            return 3  # Emergency override — 3rd patient in this slot
        return None  # Full

    @staticmethod
    async def update_status(
        db: AsyncSession, appt_id: UUID, new_status: str, **extra_fields
    ) -> Optional[Appointment]:
        """Update appointment status with optional extra fields."""
        fields = {"status": new_status, **extra_fields}
        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        fields["id"] = appt_id
        result = await db.execute(
            text(f"UPDATE appointments SET {set_clause} WHERE id = :id RETURNING *"),
            fields,
        )
        row = result.mappings().first()
        return _safe_appointment(row) if row else None

    @staticmethod
    async def get_queue(db: AsyncSession, session_id: UUID) -> List[Appointment]:
        """
        Get checked-in patients ordered for the queue.
        ORDER: is_emergency DESC, priority_tier DESC, visual_priority DESC, created_at ASC
        Emergency patients always come first regardless of other priorities.
        """
        result = await db.execute(
            text("""
                SELECT * FROM appointments
                WHERE session_id = :session_id
                  AND status = 'checked_in'
                ORDER BY
                    is_emergency DESC,
                    CASE priority_tier
                        WHEN 'CRITICAL' THEN 3
                        WHEN 'HIGH' THEN 2
                        WHEN 'NORMAL' THEN 1
                    END DESC,
                    visual_priority DESC,
                    created_at ASC
            """),
            {"session_id": session_id},
        )
        return [_safe_appointment(row) for row in result.mappings().all()]

    @staticmethod
    async def get_next_in_queue(db: AsyncSession, session_id: UUID) -> Optional[Appointment]:
        """Get the top patient in the queue (first checked-in by priority).
        Emergency patients always come first, then by priority tier, then visual_priority."""
        result = await db.execute(
            text("""
                SELECT * FROM appointments
                WHERE session_id = :session_id
                  AND status = 'checked_in'
                ORDER BY
                    is_emergency DESC,
                    CASE priority_tier
                        WHEN 'CRITICAL' THEN 3
                        WHEN 'HIGH' THEN 2
                        WHEN 'NORMAL' THEN 1
                    END DESC,
                    visual_priority DESC,
                    created_at ASC
                LIMIT 1
            """),
            {"session_id": session_id},
        )
        row = result.mappings().first()
        return _safe_appointment(row) if row else None

    @staticmethod
    async def get_by_patient(
        db: AsyncSession,
        patient_id: UUID,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Appointment]:
        """Get appointments where patient is beneficiary OR booker."""
        conditions = ["(patient_id = :pid OR booked_by_patient_id = :pid)"]
        params = {"pid": patient_id, "limit": limit, "offset": offset}
        if status:
            conditions.append("status = :status")
            params["status"] = status
        where = " AND ".join(conditions)
        result = await db.execute(
            text(f"""
                SELECT * FROM appointments
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        return [_safe_appointment(row) for row in result.mappings().all()]

    @staticmethod
    async def count_booker_today(db: AsyncSession, booker_patient_id: UUID) -> int:
        """Count today's non-cancelled bookings by this booker. For rate limiting."""
        result = await db.execute(
            text("""
                SELECT COUNT(*) FROM appointments
                WHERE booked_by_patient_id = :booker
                  AND created_at >= CURRENT_DATE
                  AND status != 'cancelled'
            """),
            {"booker": booker_patient_id},
        )
        return result.scalar()

    @staticmethod
    async def count_booker_week(db: AsyncSession, booker_patient_id: UUID) -> int:
        """Count this week's non-cancelled bookings by this booker. For rate limiting."""
        result = await db.execute(
            text("""
                SELECT COUNT(*) FROM appointments
                WHERE booked_by_patient_id = :booker
                  AND created_at >= CURRENT_DATE - INTERVAL '7 days'
                  AND status != 'cancelled'
            """),
            {"booker": booker_patient_id},
        )
        return result.scalar()

    @staticmethod
    async def mark_no_shows(db: AsyncSession, session_id: UUID) -> int:
        """Mark all 'booked' appointments as no_show after session ends."""
        result = await db.execute(
            text("""
                UPDATE appointments
                SET status = 'no_show'
                WHERE session_id = :session_id
                  AND status = 'booked'
            """),
            {"session_id": session_id},
        )
        return result.rowcount
