"""
GO Model: patient_relationships
Multi-beneficiary support.
Links a booker to people they can book for.
Must be approved by beneficiary before use.
"""
from uuid import UUID
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class PatientRelationship:
    id: UUID
    booker_patient_id: UUID
    beneficiary_patient_id: UUID
    relationship_type: str
    is_approved: bool
    approved_at: Optional[datetime]
    created_at: datetime


class RelationshipModel:

    @staticmethod
    async def create(
        db: AsyncSession,
        booker_patient_id: UUID,
        beneficiary_patient_id: UUID,
        relationship_type: str,
    ) -> PatientRelationship:
        # Self-relationships auto-approve
        is_approved = relationship_type == "self"
        approved_at = "NOW()" if is_approved else None

        result = await db.execute(
            text("""
                INSERT INTO patient_relationships
                    (booker_patient_id, beneficiary_patient_id, relationship_type,
                     is_approved, approved_at)
                VALUES
                    (:booker, :beneficiary, :rel_type,
                     :is_approved, CASE WHEN :is_approved THEN NOW() ELSE NULL END)
                RETURNING *
            """),
            {
                "booker": booker_patient_id,
                "beneficiary": beneficiary_patient_id,
                "rel_type": relationship_type,
                "is_approved": is_approved,
            },
        )
        row = result.mappings().one()
        return PatientRelationship(**row)

    @staticmethod
    async def approve(db: AsyncSession, relationship_id: UUID) -> Optional[PatientRelationship]:
        result = await db.execute(
            text("""
                UPDATE patient_relationships
                SET is_approved = true, approved_at = NOW()
                WHERE id = :id AND is_approved = false
                RETURNING *
            """),
            {"id": relationship_id},
        )
        row = result.mappings().first()
        await db.commit()  # Persist changes to database
        return PatientRelationship(**row) if row else None

    @staticmethod
    async def check_approved(
        db: AsyncSession,
        booker_patient_id: UUID,
        beneficiary_patient_id: UUID,
    ) -> bool:
        """Check if booker has approved relationship with beneficiary."""
        result = await db.execute(
            text("""
                SELECT 1 FROM patient_relationships
                WHERE booker_patient_id = :booker
                  AND beneficiary_patient_id = :beneficiary
                  AND is_approved = true
                LIMIT 1
            """),
            {"booker": booker_patient_id, "beneficiary": beneficiary_patient_id},
        )
        return result.first() is not None

    @staticmethod
    async def check_exists(
        db: AsyncSession,
        booker_patient_id: UUID,
        beneficiary_patient_id: UUID,
    ) -> bool:
        """Check if ANY relationship exists (pending or approved)."""
        result = await db.execute(
            text("""
                SELECT 1 FROM patient_relationships
                WHERE booker_patient_id = :booker
                  AND beneficiary_patient_id = :beneficiary
                LIMIT 1
            """),
            {"booker": booker_patient_id, "beneficiary": beneficiary_patient_id},
        )
        return result.first() is not None

    @staticmethod
    async def get_beneficiaries(
        db: AsyncSession, booker_patient_id: UUID
    ) -> List[PatientRelationship]:
        result = await db.execute(
            text("""
                SELECT * FROM patient_relationships
                WHERE booker_patient_id = :booker
                ORDER BY relationship_type, created_at
            """),
            {"booker": booker_patient_id},
        )
        return [PatientRelationship(**row) for row in result.mappings().all()]

    @staticmethod
    async def get_by_id(db: AsyncSession, rel_id: UUID) -> Optional[PatientRelationship]:
        result = await db.execute(
            text("SELECT * FROM patient_relationships WHERE id = :id"),
            {"id": rel_id},
        )
        row = result.mappings().first()
        return PatientRelationship(**row) if row else None

    @staticmethod
    async def delete(db: AsyncSession, rel_id: UUID) -> bool:
        result = await db.execute(
            text("DELETE FROM patient_relationships WHERE id = :id"),
            {"id": rel_id},
        )
        await db.commit()  # Persist changes to database
        return result.rowcount > 0
