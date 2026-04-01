"""
LO Model: booking_audit_log
Complete audit trail. Every action creates an entry. Never deleted.
"""
from uuid import UUID
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Any, List
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import json


@dataclass
class AuditLogEntry:
    id: UUID
    action: str
    appointment_id: Optional[UUID]
    performed_by_user_id: UUID
    patient_id: Optional[UUID]
    metadata: Optional[dict]
    ip_address: Optional[str]
    created_at: datetime


class AuditModel:

    @staticmethod
    async def create(
        db: AsyncSession,
        action: str,
        performed_by_user_id: UUID,
        appointment_id: Optional[UUID] = None,
        patient_id: Optional[UUID] = None,
        metadata: Optional[dict] = None,
        ip_address: Optional[str] = None,
    ) -> AuditLogEntry:
        result = await db.execute(
            text("""
                INSERT INTO booking_audit_log
                    (action, appointment_id, performed_by_user_id,
                     patient_id, metadata, ip_address)
                VALUES
                    (:action, :appt_id, :performed_by,
                     :patient_id, :metadata, CAST(:ip AS inet))
                RETURNING *
            """),
            {
                "action": action,
                "appt_id": appointment_id,
                "performed_by": performed_by_user_id,
                "patient_id": patient_id,
                "metadata": json.dumps(metadata) if metadata else None,
                "ip": ip_address,
            },
        )
        row = result.mappings().one()
        return AuditLogEntry(**row)

    @staticmethod
    async def get_by_appointment(
        db: AsyncSession, appointment_id: UUID
    ) -> List[AuditLogEntry]:
        result = await db.execute(
            text("""
                SELECT * FROM booking_audit_log
                WHERE appointment_id = :appt_id
                ORDER BY created_at ASC
            """),
            {"appt_id": appointment_id},
        )
        return [AuditLogEntry(**row) for row in result.mappings().all()]

    @staticmethod
    async def get_by_user(
        db: AsyncSession, user_id: UUID, limit: int = 50
    ) -> List[AuditLogEntry]:
        result = await db.execute(
            text("""
                SELECT * FROM booking_audit_log
                WHERE performed_by_user_id = :uid
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            {"uid": user_id, "limit": limit},
        )
        return [AuditLogEntry(**row) for row in result.mappings().all()]

    @staticmethod
    async def search(
        db: AsyncSession,
        action: Optional[str] = None,
        user_id: Optional[UUID] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[AuditLogEntry]:
        conditions = []
        params = {"limit": limit, "offset": offset}
        if action:
            conditions.append("action = :action")
            params["action"] = action
        if user_id:
            conditions.append("performed_by_user_id = :uid")
            params["uid"] = user_id
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        result = await db.execute(
            text(f"""
                SELECT * FROM booking_audit_log
                {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        return [AuditLogEntry(**row) for row in result.mappings().all()]
