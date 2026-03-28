"""
LO Model: doctor_ratings
Post-visit feedback. One rating per appointment.
Review text gets embedded in ChromaDB for RAG.
"""
from uuid import UUID
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List
from decimal import Decimal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class DoctorRating:
    id: UUID
    appointment_id: UUID
    patient_id: UUID
    doctor_id: UUID
    rating: int
    review: Optional[str]
    sentiment_score: Optional[Decimal]
    created_at: datetime


class RatingModel:

    @staticmethod
    async def create(
        db: AsyncSession,
        appointment_id: UUID,
        patient_id: UUID,
        doctor_id: UUID,
        rating: int,
        review: Optional[str] = None,
        sentiment_score: Optional[Decimal] = None,
    ) -> DoctorRating:
        result = await db.execute(
            text("""
                INSERT INTO doctor_ratings
                    (appointment_id, patient_id, doctor_id, rating, review, sentiment_score)
                VALUES
                    (:appt_id, :patient_id, :doctor_id, :rating, :review, :sentiment)
                RETURNING *
            """),
            {
                "appt_id": appointment_id,
                "patient_id": patient_id,
                "doctor_id": doctor_id,
                "rating": rating,
                "review": review,
                "sentiment": sentiment_score,
            },
        )
        row = result.mappings().one()
        return DoctorRating(**row)

    @staticmethod
    async def get_by_doctor(
        db: AsyncSession, doctor_id: UUID, limit: int = 50, offset: int = 0
    ) -> List[DoctorRating]:
        result = await db.execute(
            text("""
                SELECT * FROM doctor_ratings
                WHERE doctor_id = :did
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"did": doctor_id, "limit": limit, "offset": offset},
        )
        return [DoctorRating(**row) for row in result.mappings().all()]

    @staticmethod
    async def get_avg_rating(db: AsyncSession, doctor_id: UUID) -> dict:
        """Get average rating and count for a doctor."""
        result = await db.execute(
            text("""
                SELECT
                    COALESCE(AVG(rating), 0) as avg_rating,
                    COUNT(*) as total_ratings
                FROM doctor_ratings
                WHERE doctor_id = :did
            """),
            {"did": doctor_id},
        )
        row = result.mappings().one()
        return {"avg_rating": float(row["avg_rating"]), "total_ratings": row["total_ratings"]}

    @staticmethod
    async def get_by_appointment(
        db: AsyncSession, appointment_id: UUID
    ) -> Optional[DoctorRating]:
        result = await db.execute(
            text("SELECT * FROM doctor_ratings WHERE appointment_id = :appt_id"),
            {"appt_id": appointment_id},
        )
        row = result.mappings().first()
        return DoctorRating(**row) if row else None
