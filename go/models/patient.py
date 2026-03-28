"""
GO Model: patients
Patient medical profile. Extends users.
Contains DOB for auto-priority and risk_score for rate limiting.
"""
from uuid import UUID
from datetime import datetime, date
from dataclasses import dataclass
from typing import Optional
from decimal import Decimal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class Patient:
    id: UUID
    user_id: UUID
    abha_id: Optional[str]  # 14-digit UHID (dummy for local)
    date_of_birth: date
    gender: str
    blood_group: Optional[str]
    emergency_contact_name: Optional[str]
    emergency_contact_phone: Optional[str]
    address: Optional[str]
    risk_score: Decimal
    created_at: datetime
    updated_at: datetime


class PatientModel:

    @staticmethod
    async def create(
        db: AsyncSession,
        user_id: UUID,
        date_of_birth: date,
        gender: str,
        abha_id: Optional[str] = None,
        blood_group: Optional[str] = None,
        emergency_contact_name: Optional[str] = None,
        emergency_contact_phone: Optional[str] = None,
        address: Optional[str] = None,
    ) -> Patient:
        result = await db.execute(
            text("""
                INSERT INTO patients
                    (user_id, date_of_birth, gender, abha_id, blood_group,
                     emergency_contact_name, emergency_contact_phone, address)
                VALUES
                    (:user_id, :dob, :gender, :abha_id, :blood_group,
                     :ec_name, :ec_phone, :address)
                RETURNING *
            """),
            {
                "user_id": user_id,
                "dob": date_of_birth,
                "gender": gender,
                "abha_id": abha_id,
                "blood_group": blood_group,
                "ec_name": emergency_contact_name,
                "ec_phone": emergency_contact_phone,
                "address": address,
            },
        )
        row = result.mappings().one()
        return Patient(**row)

    @staticmethod
    async def get_by_id(db: AsyncSession, patient_id: UUID) -> Optional[Patient]:
        result = await db.execute(
            text("SELECT * FROM patients WHERE id = :id"),
            {"id": patient_id},
        )
        row = result.mappings().first()
        return Patient(**row) if row else None

    @staticmethod
    async def get_by_user_id(db: AsyncSession, user_id: UUID) -> Optional[Patient]:
        result = await db.execute(
            text("SELECT * FROM patients WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        row = result.mappings().first()
        return Patient(**row) if row else None

    @staticmethod
    async def get_by_abha_id(db: AsyncSession, abha_id: str) -> Optional[Patient]:
        result = await db.execute(
            text("SELECT * FROM patients WHERE abha_id = :abha_id"),
            {"abha_id": abha_id},
        )
        row = result.mappings().first()
        return Patient(**row) if row else None

    @staticmethod
    async def update_risk_score(
        db: AsyncSession, patient_id: UUID, delta: Decimal
    ) -> Optional[Patient]:
        """Add delta to risk_score. Used by cancellation service."""
        result = await db.execute(
            text("""
                UPDATE patients
                SET risk_score = risk_score + :delta
                WHERE id = :id
                RETURNING *
            """),
            {"id": patient_id, "delta": delta},
        )
        row = result.mappings().first()
        return Patient(**row) if row else None

    @staticmethod
    async def decay_all_risk_scores(db: AsyncSession, decay_amount: Decimal) -> int:
        """
        Nightly cron job: reduce all positive risk scores.
        Returns number of patients updated.
        """
        result = await db.execute(
            text("""
                UPDATE patients
                SET risk_score = GREATEST(risk_score - :decay, 0)
                WHERE risk_score > 0
            """),
            {"decay": decay_amount},
        )
        return result.rowcount

    @staticmethod
    async def update(db: AsyncSession, patient_id: UUID, **fields) -> Optional[Patient]:
        if not fields:
            return await PatientModel.get_by_id(db, patient_id)
        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        fields["id"] = patient_id
        result = await db.execute(
            text(f"UPDATE patients SET {set_clause} WHERE id = :id RETURNING *"),
            fields,
        )
        row = result.mappings().first()
        return Patient(**row) if row else None
