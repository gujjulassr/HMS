"""
LO Model: doctor_ratings
Post-visit feedback. One rating per appointment.
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

    @staticmethod
    async def get_reviews_for_search(
        db: AsyncSession, doctor_id: UUID = None, limit: int = 30
    ) -> list[dict]:
        """Get recent reviews with doctor names — used by AI search_feedback tool.

        Returns dicts with: doctor_name, rating, review, sentiment_score, created_at.
        If doctor_id is provided, filters to that doctor. Otherwise returns all.
        """
        if doctor_id:
            result = await db.execute(
                text("""
                    SELECT dr.rating, dr.review, dr.sentiment_score, dr.created_at,
                           u.full_name as doctor_name, d.specialization
                    FROM doctor_ratings dr
                    JOIN doctors d ON dr.doctor_id = d.id
                    JOIN users u ON d.user_id = u.id
                    WHERE dr.doctor_id = :did AND dr.review IS NOT NULL AND dr.review != ''
                    ORDER BY dr.created_at DESC
                    LIMIT :limit
                """),
                {"did": doctor_id, "limit": limit},
            )
        else:
            result = await db.execute(
                text("""
                    SELECT dr.rating, dr.review, dr.sentiment_score, dr.created_at,
                           u.full_name as doctor_name, d.specialization
                    FROM doctor_ratings dr
                    JOIN doctors d ON dr.doctor_id = d.id
                    JOIN users u ON d.user_id = u.id
                    WHERE dr.review IS NOT NULL AND dr.review != ''
                    ORDER BY dr.created_at DESC
                    LIMIT :limit
                """),
                {"limit": limit},
            )
        return [dict(row) for row in result.mappings().all()]
