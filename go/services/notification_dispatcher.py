"""
Notification Dispatcher — hooks into routes to send email notifications.

This module is called AFTER successful operations (booking, cancellation, etc.)
to dispatch emails in the background. It never blocks or modifies the core flow.

Usage in routes:
    from go.services.notification_dispatcher import notify_booking, notify_cancellation
    # After successful booking:
    notify_booking(db, appointment_id)
"""

import logging
import asyncio
from uuid import UUID
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from go.services.email_service import (
    send_booking_confirmation,
    send_cancellation_email,
    send_delay_notification,
    send_session_cancelled_email,
    send_email_background,
)

logger = logging.getLogger(__name__)


async def _get_appointment_email_context(db: AsyncSession, appointment_id: UUID) -> Optional[dict]:
    """
    Fetch all info needed to send an email about an appointment.
    Returns dict with patient_name, email, doctor_name, specialization, date, time, slot.
    """
    result = await db.execute(
        text("""
            SELECT
                u_p.full_name AS patient_name, u_p.email AS patient_email,
                u_d.full_name AS doctor_name, d.specialization,
                s.session_date, s.start_time, s.slot_duration_minutes,
                a.slot_number, a.status
            FROM appointments a
            JOIN patients p ON a.patient_id = p.id
            JOIN users u_p ON p.user_id = u_p.id
            JOIN sessions s ON a.session_id = s.id
            JOIN doctors d ON s.doctor_id = d.id
            JOIN users u_d ON d.user_id = u_d.id
            WHERE a.id = :aid
        """),
        {"aid": appointment_id},
    )
    row = result.mappings().first()
    if not row:
        return None

    # Calculate slot time
    try:
        start = row["start_time"]
        dur = row["slot_duration_minutes"]
        slot = row["slot_number"]
        hh = start.hour if hasattr(start, 'hour') else int(str(start)[:2])
        mm = start.minute if hasattr(start, 'minute') else int(str(start)[3:5])
        total_min = hh * 60 + mm + (slot - 1) * dur
        slot_time = f"{total_min // 60:02d}:{total_min % 60:02d}"
    except Exception:
        slot_time = "—"

    return {
        "appointment_id": str(appointment_id),
        "patient_name": row["patient_name"],
        "patient_email": row["patient_email"],
        "doctor_name": row["doctor_name"],
        "specialization": row["specialization"],
        "session_date": str(row["session_date"]),
        "slot_time": slot_time,
        "slot_number": row["slot_number"],
        "duration_minutes": row["slot_duration_minutes"],
    }


async def notify_booking(db: AsyncSession, appointment_id):
    """
    Fetch email context now (while db session is alive), then fire-and-forget the send.
    """
    try:
        ctx = await _get_appointment_email_context(db, UUID(str(appointment_id)))
        if not ctx or not ctx.get("patient_email"):
            return
        if "@dpms.local" in ctx["patient_email"]:
            return
    except Exception as e:
        logger.error("notify_booking context error: %s", e)
        return

    async def _send():
        try:
            await send_booking_confirmation(
                to_email=ctx["patient_email"],
                patient_name=ctx["patient_name"],
                doctor_name=ctx["doctor_name"],
                specialization=ctx["specialization"],
                session_date=ctx["session_date"],
                slot_time=ctx["slot_time"],
                slot_number=ctx["slot_number"],
                appointment_id=ctx["appointment_id"],
                duration_minutes=ctx.get("duration_minutes", 15),
            )
        except Exception as e:
            logger.error("notify_booking send error: %s", e)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_send())
    except RuntimeError:
        pass


async def notify_cancellation(db: AsyncSession, appointment_id, reason: str = ""):
    """
    Fetch email context now (while db session is alive), then fire-and-forget the send.
    """
    try:
        ctx = await _get_appointment_email_context(db, UUID(str(appointment_id)))
        if not ctx or not ctx.get("patient_email"):
            return
        if "@dpms.local" in ctx["patient_email"]:
            return
    except Exception as e:
        logger.error("notify_cancellation context error: %s", e)
        return

    async def _send():
        try:
            await send_cancellation_email(
                to_email=ctx["patient_email"],
                patient_name=ctx["patient_name"],
                doctor_name=ctx["doctor_name"],
                session_date=ctx["session_date"],
                slot_time=ctx["slot_time"],
                reason=reason,
                appointment_id=ctx["appointment_id"],
            )
        except Exception as e:
            logger.error("notify_cancellation send error: %s", e)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_send())
    except RuntimeError:
        pass


async def notify_delay_for_session(db: AsyncSession, session_id: UUID, delay_minutes: int):
    """
    Send delay notifications to all patients with upcoming (booked/checked_in)
    appointments in this session.
    """
    try:
        result = await db.execute(
            text("""
                SELECT u.full_name AS patient_name, u.email AS patient_email,
                       u_d.full_name AS doctor_name,
                       s.session_date, s.start_time, s.slot_duration_minutes,
                       a.slot_number
                FROM appointments a
                JOIN patients p ON a.patient_id = p.id
                JOIN users u ON p.user_id = u.id
                JOIN sessions s ON a.session_id = s.id
                JOIN doctors d ON s.doctor_id = d.id
                JOIN users u_d ON d.user_id = u_d.id
                WHERE a.session_id = :sid
                  AND a.status IN ('booked', 'checked_in')
            """),
            {"sid": session_id},
        )
        rows = result.mappings().all()

        for row in rows:
            email = row["patient_email"]
            if not email or "@dpms.local" in email:
                continue
            try:
                start = row["start_time"]
                dur = row["slot_duration_minutes"]
                slot = row["slot_number"]
                hh = start.hour if hasattr(start, 'hour') else int(str(start)[:2])
                mm = start.minute if hasattr(start, 'minute') else int(str(start)[3:5])
                total_min = hh * 60 + mm + (slot - 1) * dur
                slot_time = f"{total_min // 60:02d}:{total_min % 60:02d}"
            except Exception:
                slot_time = "—"

            await send_delay_notification(
                to_email=email,
                patient_name=row["patient_name"],
                doctor_name=row["doctor_name"],
                session_date=str(row["session_date"]),
                original_time=slot_time,
                estimated_delay_minutes=delay_minutes,
            )

        logger.info("Delay notifications sent for session %s (%d patients)", session_id, len(rows))
    except Exception as e:
        logger.error("notify_delay_for_session error: %s", e)


async def notify_session_cancelled(db: AsyncSession, session_id: UUID, reason: str = ""):
    """Send cancellation emails to all patients when an entire session is cancelled."""
    try:
        result = await db.execute(
            text("""
                SELECT DISTINCT u.full_name AS patient_name, u.email AS patient_email,
                       u_d.full_name AS doctor_name, s.session_date
                FROM appointments a
                JOIN patients p ON a.patient_id = p.id
                JOIN users u ON p.user_id = u.id
                JOIN sessions s ON a.session_id = s.id
                JOIN doctors d ON s.doctor_id = d.id
                JOIN users u_d ON d.user_id = u_d.id
                WHERE a.session_id = :sid
            """),
            {"sid": session_id},
        )
        rows = result.mappings().all()
        for row in rows:
            email = row["patient_email"]
            if not email or "@dpms.local" in email:
                continue
            await send_session_cancelled_email(
                to_email=email,
                patient_name=row["patient_name"],
                doctor_name=row["doctor_name"],
                session_date=str(row["session_date"]),
                reason=reason,
            )
        logger.info("Session cancel notifications sent for %s (%d patients)", session_id, len(rows))
    except Exception as e:
        logger.error("notify_session_cancelled error: %s", e)
