"""
GO Model: sessions
Doctor availability windows. Divided into slots.
On-the-fly availability — no pre-generated slot rows.
Available = total_slots * max_patients_per_slot - booked_count
"""
from uuid import UUID
from datetime import datetime, date, time
from dataclasses import dataclass
from typing import Optional, List
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class Session:
    id: UUID
    doctor_id: UUID
    session_date: date
    start_time: time
    end_time: time
    slot_duration_minutes: int
    max_patients_per_slot: int
    scheduling_type: str
    total_slots: int
    booked_count: int
    doctor_checkin_at: Optional[datetime] = None
    actual_end_time: Optional[time] = None
    delay_minutes: int = 0
    notes: Optional[str] = None
    status: str = "active"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        # DB may return float for delay_minutes from EXTRACT
        if self.delay_minutes is not None:
            self.delay_minutes = int(self.delay_minutes)
        else:
            self.delay_minutes = 0


class SessionModel:

    @staticmethod
    def compute_total_slots(start_time: time, end_time: time, duration_minutes: int) -> int:
        """Calculate number of slots from time range and duration."""
        start_minutes = start_time.hour * 60 + start_time.minute
        end_minutes = end_time.hour * 60 + end_time.minute
        return (end_minutes - start_minutes) // duration_minutes

    @staticmethod
    async def create(
        db: AsyncSession,
        doctor_id: UUID,
        session_date: date,
        start_time: time,
        end_time: time,
        slot_duration_minutes: int = 15,
        max_patients_per_slot: int = 2,
        scheduling_type: str = "TIME_SLOT",
    ) -> Session:
        total_slots = SessionModel.compute_total_slots(
            start_time, end_time, slot_duration_minutes
        )
        result = await db.execute(
            text("""
                INSERT INTO sessions
                    (doctor_id, session_date, start_time, end_time,
                     slot_duration_minutes, max_patients_per_slot,
                     scheduling_type, total_slots)
                VALUES
                    (:doctor_id, :date, :start, :end,
                     :duration, :max_pps, :sched_type, :total_slots)
                RETURNING *
            """),
            {
                "doctor_id": doctor_id,
                "date": session_date,
                "start": start_time,
                "end": end_time,
                "duration": slot_duration_minutes,
                "max_pps": max_patients_per_slot,
                "sched_type": scheduling_type,
                "total_slots": total_slots,
            },
        )
        row = result.mappings().one()
        return Session(**row)

    @staticmethod
    async def get_by_id(db: AsyncSession, session_id: UUID) -> Optional[Session]:
        result = await db.execute(
            text("SELECT * FROM sessions WHERE id = :id"),
            {"id": session_id},
        )
        row = result.mappings().first()
        return Session(**row) if row else None

    @staticmethod
    async def get_by_id_for_update(db: AsyncSession, session_id: UUID) -> Optional[Session]:
        """SELECT FOR UPDATE — locks the row for concurrent booking/cancel safety."""
        result = await db.execute(
            text("SELECT * FROM sessions WHERE id = :id FOR UPDATE"),
            {"id": session_id},
        )
        row = result.mappings().first()
        return Session(**row) if row else None

    @staticmethod
    async def get_by_doctor_date(
        db: AsyncSession,
        doctor_id: UUID,
        session_date: date,
        status: str = "active",
    ) -> List[Session]:
        result = await db.execute(
            text("""
                SELECT * FROM sessions
                WHERE doctor_id = :doctor_id
                  AND session_date = :date
                  AND status = :status
                ORDER BY start_time
            """),
            {"doctor_id": doctor_id, "date": session_date, "status": status},
        )
        return [Session(**row) for row in result.mappings().all()]

    @staticmethod
    async def get_available_sessions(
        db: AsyncSession,
        doctor_id: Optional[UUID] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Session]:
        """List active sessions with available capacity."""
        conditions = ["s.status = 'active'"]
        params = {"limit": limit, "offset": offset}

        if doctor_id:
            conditions.append("s.doctor_id = :doctor_id")
            params["doctor_id"] = doctor_id
        if date_from:
            conditions.append("s.session_date >= :date_from")
            params["date_from"] = date_from
        if date_to:
            conditions.append("s.session_date <= :date_to")
            params["date_to"] = date_to

        where = " AND ".join(conditions)
        result = await db.execute(
            text(f"""
                SELECT s.* FROM sessions s
                WHERE {where}
                  AND s.booked_count < (s.total_slots * s.max_patients_per_slot)
                ORDER BY s.session_date, s.start_time
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        return [Session(**row) for row in result.mappings().all()]

    @staticmethod
    async def get_all_sessions(
        db: AsyncSession,
        doctor_id: Optional[UUID] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> List[Session]:
        """List ALL sessions (any status) for a doctor on given dates."""
        conditions = ["1=1"]
        params: dict = {}
        if doctor_id:
            conditions.append("s.doctor_id = :doctor_id")
            params["doctor_id"] = doctor_id
        if date_from:
            conditions.append("s.session_date >= :date_from")
            params["date_from"] = date_from
        if date_to:
            conditions.append("s.session_date <= :date_to")
            params["date_to"] = date_to
        where = " AND ".join(conditions)
        result = await db.execute(
            text(f"SELECT s.* FROM sessions s WHERE {where} ORDER BY s.session_date, s.start_time"),
            params,
        )
        return [Session(**row) for row in result.mappings().all()]

    @staticmethod
    async def update_booked_count(
        db: AsyncSession, session_id: UUID, delta: int
    ) -> Optional[Session]:
        """Increment (+1) or decrement (-1) the booked_count counter."""
        result = await db.execute(
            text("""
                UPDATE sessions
                SET booked_count = booked_count + :delta
                WHERE id = :id
                RETURNING *
            """),
            {"id": session_id, "delta": delta},
        )
        row = result.mappings().first()
        return Session(**row) if row else None

    # ─── Real-time: Doctor Check-in & Overtime ────────────────

    @staticmethod
    async def doctor_checkin(db: AsyncSession, session_id: UUID) -> Optional[Session]:
        """
        Mark when doctor actually starts seeing patients.
        Auto-computes delay_minutes from scheduled start_time.
        """
        result = await db.execute(
            text("""
                UPDATE sessions
                SET doctor_checkin_at = NOW(),
                    delay_minutes = GREATEST(0, ROUND(EXTRACT(EPOCH FROM (NOW()::time - start_time)) / 60)::integer),
                    notes = CASE
                        WHEN EXTRACT(EPOCH FROM (NOW()::time - start_time)) / 60 > 5
                        THEN 'Doctor running ' ||
                             GREATEST(0, ROUND(EXTRACT(EPOCH FROM (NOW()::time - start_time)) / 60)::integer) ||
                             ' min late'
                        ELSE 'Doctor checked in on time'
                    END
                WHERE id = :id AND status = 'active'
                RETURNING *
            """),
            {"id": session_id},
        )
        row = result.mappings().first()
        return Session(**row) if row else None

    @staticmethod
    async def extend_session(
        db: AsyncSession, session_id: UUID, new_end_time: time, note: str = None
    ) -> Optional[Session]:
        """
        Doctor decides to stay late (overtime) — extend session end time.
        Recalculates total_slots based on new end time.
        """
        note_val = note if note else f"Session extended to {new_end_time}"
        result = await db.execute(
            text("""
                UPDATE sessions
                SET end_time = :new_end,
                    actual_end_time = :new_end,
                    total_slots = EXTRACT(EPOCH FROM (:new_end - start_time)) / 60
                                  / slot_duration_minutes,
                    notes = :note_val
                WHERE id = :id AND status = 'active'
                RETURNING *
            """),
            {"id": session_id, "new_end": new_end_time, "note_val": note_val},
        )
        row = result.mappings().first()
        return Session(**row) if row else None

    @staticmethod
    async def cancel_session(db: AsyncSession, session_id: UUID) -> bool:
        result = await db.execute(
            text("UPDATE sessions SET status = 'cancelled' WHERE id = :id AND status = 'active'"),
            {"id": session_id},
        )
        return result.rowcount > 0

    @staticmethod
    async def complete_session(db: AsyncSession, session_id: UUID) -> bool:
        result = await db.execute(
            text("UPDATE sessions SET status = 'completed' WHERE id = :id AND status = 'active'"),
            {"id": session_id},
        )
        return result.rowcount > 0

    @staticmethod
    async def activate_session(db: AsyncSession, session_id: UUID) -> bool:
        """Activate an inactive session so patients can book into it."""
        result = await db.execute(
            text("UPDATE sessions SET status = 'active' WHERE id = :id AND status = 'inactive'"),
            {"id": session_id},
        )
        return result.rowcount > 0
