"""
GO Model: doctors
Doctor profile and consultation settings.
max_patients_per_slot is the default for new sessions.
"""
from uuid import UUID
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List
from decimal import Decimal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class Doctor:
    id: UUID
    user_id: UUID
    specialization: str
    qualification: str
    license_number: str
    consultation_fee: Decimal
    max_patients_per_slot: int
    is_available: bool
    created_at: datetime
    updated_at: datetime


class DoctorModel:

    @staticmethod
    async def create(
        db: AsyncSession,
        user_id: UUID,
        specialization: str,
        qualification: str,
        license_number: str,
        consultation_fee: Decimal,
        max_patients_per_slot: int = 2,
    ) -> Doctor:
        result = await db.execute(
            text("""
                INSERT INTO doctors
                    (user_id, specialization, qualification, license_number,
                     consultation_fee, max_patients_per_slot)
                VALUES
                    (:user_id, :spec, :qual, :license, :fee, :max_pps)
                RETURNING *
            """),
            {
                "user_id": user_id,
                "spec": specialization,
                "qual": qualification,
                "license": license_number,
                "fee": consultation_fee,
                "max_pps": max_patients_per_slot,
            },
        )
        row = result.mappings().one()
        return Doctor(**row)

    @staticmethod
    async def get_by_id(db: AsyncSession, doctor_id: UUID) -> Optional[Doctor]:
        result = await db.execute(
            text("SELECT * FROM doctors WHERE id = :id"),
            {"id": doctor_id},
        )
        row = result.mappings().first()
        return Doctor(**row) if row else None

    @staticmethod
    async def get_by_user_id(db: AsyncSession, user_id: UUID) -> Optional[Doctor]:
        result = await db.execute(
            text("SELECT * FROM doctors WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        row = result.mappings().first()
        return Doctor(**row) if row else None

    @staticmethod
    async def list_by_specialization(
        db: AsyncSession,
        specialization: Optional[str] = None,
        only_available: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Doctor]:
        conditions = ["u.is_active = true"]
        params = {"limit": limit, "offset": offset}

        if only_available:
            conditions.append("d.is_available = true")
        if specialization:
            conditions.append("d.specialization ILIKE :spec")
            params["spec"] = f"%{specialization}%"

        where = "WHERE " + " AND ".join(conditions)
        result = await db.execute(
            text(f"""
                SELECT d.* FROM doctors d
                JOIN users u ON d.user_id = u.id
                {where}
                ORDER BY d.specialization, u.full_name
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        return [Doctor(**row) for row in result.mappings().all()]

    @staticmethod
    async def toggle_availability(db: AsyncSession, doctor_id: UUID, available: bool) -> bool:
        result = await db.execute(
            text("UPDATE doctors SET is_available = :avail WHERE id = :id"),
            {"id": doctor_id, "avail": available},
        )
        return result.rowcount > 0
