"""
Notification Dispatcher — hooks into routes to send email notifications.

This module is called AFTER successful operations (booking, cancellation, etc.)
to dispatch emails in the background. It never blocks or modifies the core flow.

Every email is logged to notification_log:
  1. Create a 'pending' record BEFORE sending (while the route's db session is alive)
  2. Update to 'sent' or 'failed' after the email attempt

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
    send_no_show_email,
)
from lo.models.notification_log import NotificationModel
from database import async_session

logger = logging.getLogger(__name__)


# ─── Helpers ────────────────────────────────────────────────────

async def _log_pending(db: AsyncSession, user_id: UUID, notif_type: str,
                       content: str, appointment_id: Optional[UUID] = None) -> Optional[UUID]:
    """Create a 'pending' notification_log record. Returns log_id or None on error."""
    try:
        log = await NotificationModel.create(
            db, user_id=user_id, type=notif_type, channel="email",
            content=content, appointment_id=appointment_id,
        )
        return log.id
    except Exception as e:
        logger.error("Failed to create notification_log (type=%s): %s", notif_type, e)
        return None


async def _mark_sent(db: AsyncSession, log_id: UUID):
    """Mark a notification_log record as 'sent'."""
    try:
        await NotificationModel.update_status(db, log_id, "sent")
    except Exception as e:
        logger.error("Failed to mark notification %s as sent: %s", log_id, e)


async def _mark_failed(db: AsyncSession, log_id: UUID, error: str):
    """Mark a notification_log record as 'failed'."""
    try:
        await NotificationModel.update_status(db, log_id, "failed", error_message=error)
    except Exception as e:
        logger.error("Failed to mark notification %s as failed: %s", log_id, e)


async def _update_log_own_session(log_id: UUID, success: bool, error_msg: str = ""):
    """Open a fresh db session to update log status (for fire-and-forget tasks)."""
    try:
        async with async_session() as db:
            if success:
                await _mark_sent(db, log_id)
            else:
                await _mark_failed(db, log_id, error_msg)
            await db.commit()
    except Exception as e:
        logger.error("_update_log_own_session error for %s: %s", log_id, e)


def _calc_slot_time(row) -> str:
    """Calculate slot time string from a DB row."""
    try:
        start = row["start_time"]
        dur = row["slot_duration_minutes"]
        slot = row["slot_number"]
        hh = start.hour if hasattr(start, 'hour') else int(str(start)[:2])
        mm = start.minute if hasattr(start, 'minute') else int(str(start)[3:5])
        total_min = hh * 60 + mm + (slot - 1) * dur
        return f"{total_min // 60:02d}:{total_min % 60:02d}"
    except Exception:
        return "—"


# ─── Email context query ────────────────────────────────────────

async def _get_appointment_email_context(db: AsyncSession, appointment_id: UUID) -> Optional[dict]:
    """
    Fetch all info needed to send an email about an appointment.
    Returns dict with patient_name, email, doctor_name, specialization, date, time, slot,
    and patient_user_id (needed for notification_log).
    """
    result = await db.execute(
        text("""
            SELECT
                u_p.id AS patient_user_id,
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

    return {
        "appointment_id": str(appointment_id),
        "patient_user_id": row["patient_user_id"],
        "patient_name": row["patient_name"],
        "patient_email": row["patient_email"],
        "doctor_name": row["doctor_name"],
        "specialization": row["specialization"],
        "session_date": str(row["session_date"]),
        "slot_time": _calc_slot_time(row),
        "slot_number": row["slot_number"],
        "duration_minutes": row["slot_duration_minutes"],
    }


# ─── Dispatchers ────────────────────────────────────────────────

async def notify_booking(db: AsyncSession, appointment_id):
    """
    Fetch email context now (while db session is alive), log as 'pending',
    then fire-and-forget the send. The _send task updates status with its own session.
    """
    try:
        ctx = await _get_appointment_email_context(db, UUID(str(appointment_id)))
        if not ctx:
            logger.warning("notify_booking: no context found for appointment %s", appointment_id)
            return
        if not ctx.get("patient_email"):
            logger.warning("notify_booking: no patient email for appointment %s", appointment_id)
            return
        if "@dpms.local" in ctx["patient_email"]:
            logger.info("notify_booking: skipping @dpms.local email for %s", appointment_id)
            return
        logger.info("notify_booking: sending to %s for appointment %s", ctx["patient_email"], appointment_id)
    except Exception as e:
        logger.error("notify_booking context error: %s", e, exc_info=True)
        return

    # Log as 'pending' while db session is alive
    log_id = await _log_pending(
        db,
        user_id=ctx["patient_user_id"],
        notif_type="booking_confirmation",
        content=f"Booking confirmed with Dr. {ctx['doctor_name']} on {ctx['session_date']} at {ctx['slot_time']}",
        appointment_id=UUID(ctx["appointment_id"]),
    )

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
            if log_id:
                await _update_log_own_session(log_id, success=True)
        except Exception as e:
            logger.error("notify_booking send error: %s", e)
            if log_id:
                await _update_log_own_session(log_id, success=False, error_msg=str(e))

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_send())
    except RuntimeError:
        pass


async def notify_cancellation(db: AsyncSession, appointment_id, reason: str = ""):
    """
    Fetch email context now (while db session is alive), log as 'pending',
    then fire-and-forget the send.
    """
    try:
        ctx = await _get_appointment_email_context(db, UUID(str(appointment_id)))
        if not ctx:
            logger.warning("notify_cancellation: no context found for appointment %s", appointment_id)
            return
        if not ctx.get("patient_email"):
            logger.warning("notify_cancellation: no patient email for appointment %s", appointment_id)
            return
        if "@dpms.local" in ctx["patient_email"]:
            logger.info("notify_cancellation: skipping @dpms.local email for %s", appointment_id)
            return
        logger.info("notify_cancellation: sending to %s for appointment %s", ctx["patient_email"], appointment_id)
    except Exception as e:
        logger.error("notify_cancellation context error: %s", e, exc_info=True)
        return

    # Log as 'pending' while db session is alive
    log_id = await _log_pending(
        db,
        user_id=ctx["patient_user_id"],
        notif_type="cancellation",
        content=f"Appointment with Dr. {ctx['doctor_name']} on {ctx['session_date']} cancelled. {reason}".strip(),
        appointment_id=UUID(ctx["appointment_id"]),
    )

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
            if log_id:
                await _update_log_own_session(log_id, success=True)
        except Exception as e:
            logger.error("notify_cancellation send error: %s", e)
            if log_id:
                await _update_log_own_session(log_id, success=False, error_msg=str(e))

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
                SELECT u.id AS patient_user_id,
                       u.full_name AS patient_name, u.email AS patient_email,
                       u_d.full_name AS doctor_name,
                       s.session_date, s.start_time, s.slot_duration_minutes,
                       a.slot_number, a.id AS appointment_id
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

            slot_time = _calc_slot_time(row)

            # Log as pending
            log_id = await _log_pending(
                db,
                user_id=row["patient_user_id"],
                notif_type="DELAY_UPDATE",
                content=f"Session delayed by {delay_minutes} min. Dr. {row['doctor_name']} on {row['session_date']}",
                appointment_id=row["appointment_id"],
            )

            try:
                await send_delay_notification(
                    to_email=email,
                    patient_name=row["patient_name"],
                    doctor_name=row["doctor_name"],
                    session_date=str(row["session_date"]),
                    original_time=slot_time,
                    estimated_delay_minutes=delay_minutes,
                )
                if log_id:
                    await _mark_sent(db, log_id)
            except Exception as e:
                logger.error("notify_delay email error for %s: %s", email, e)
                if log_id:
                    await _mark_failed(db, log_id, str(e))

        logger.info("Delay notifications sent for session %s (%d patients)", session_id, len(rows))
    except Exception as e:
        logger.error("notify_delay_for_session error: %s", e)


async def notify_session_completed(db: AsyncSession, session_id: UUID,
                                    no_show_ids: list = None, cancelled_ids: list = None):
    """
    Send emails when a session is completed:
    - no_show patients (booked but never checked in) → no-show email
    - cancelled patients (checked_in but not seen) → cancellation email
    """
    no_show_ids = no_show_ids or []
    cancelled_ids = cancelled_ids or []

    try:
        # Send no-show emails
        for appt_id in no_show_ids:
            try:
                result = await db.execute(
                    text("""
                        SELECT u.id AS patient_user_id,
                               u.full_name AS patient_name, u.email AS patient_email,
                               u_d.full_name AS doctor_name,
                               s.session_date, s.start_time, s.slot_duration_minutes,
                               a.slot_number
                        FROM appointments a
                        JOIN patients p ON a.patient_id = p.id
                        JOIN users u ON p.user_id = u.id
                        JOIN sessions s ON a.session_id = s.id
                        JOIN doctors d ON s.doctor_id = d.id
                        JOIN users u_d ON d.user_id = u_d.id
                        WHERE a.id = :aid
                    """),
                    {"aid": appt_id},
                )
                row = result.mappings().first()
                if not row or not row["patient_email"] or "@dpms.local" in row["patient_email"]:
                    continue

                slot_time = _calc_slot_time(row)

                # Log as pending
                log_id = await _log_pending(
                    db,
                    user_id=row["patient_user_id"],
                    notif_type="no_show",
                    content=f"Marked as no-show for Dr. {row['doctor_name']} on {row['session_date']}",
                    appointment_id=appt_id,
                )

                try:
                    await send_no_show_email(
                        to_email=row["patient_email"],
                        patient_name=row["patient_name"],
                        doctor_name=row["doctor_name"],
                        session_date=str(row["session_date"]),
                        slot_time=slot_time,
                    )
                    if log_id:
                        await _mark_sent(db, log_id)
                except Exception as e:
                    logger.error("notify_session_completed no-show send error for %s: %s", appt_id, e)
                    if log_id:
                        await _mark_failed(db, log_id, str(e))

            except Exception as e:
                logger.error("notify_session_completed no-show email error for %s: %s", appt_id, e)

        # Send cancellation emails to checked_in patients who couldn't be seen
        for appt_id in cancelled_ids:
            try:
                result = await db.execute(
                    text("""
                        SELECT u.id AS patient_user_id,
                               u.full_name AS patient_name, u.email AS patient_email,
                               u_d.full_name AS doctor_name,
                               s.session_date, s.start_time, s.slot_duration_minutes,
                               a.slot_number
                        FROM appointments a
                        JOIN patients p ON a.patient_id = p.id
                        JOIN users u ON p.user_id = u.id
                        JOIN sessions s ON a.session_id = s.id
                        JOIN doctors d ON s.doctor_id = d.id
                        JOIN users u_d ON d.user_id = u_d.id
                        WHERE a.id = :aid
                    """),
                    {"aid": appt_id},
                )
                row = result.mappings().first()
                if not row or not row["patient_email"] or "@dpms.local" in row["patient_email"]:
                    continue

                slot_time = _calc_slot_time(row)
                reason = "Session ended before you could be seen. No penalty applied."

                # Log as pending
                log_id = await _log_pending(
                    db,
                    user_id=row["patient_user_id"],
                    notif_type="CANNOT_BE_SEEN",
                    content=f"Could not be seen by Dr. {row['doctor_name']} on {row['session_date']}. {reason}",
                    appointment_id=appt_id,
                )

                try:
                    await send_cancellation_email(
                        to_email=row["patient_email"],
                        patient_name=row["patient_name"],
                        doctor_name=row["doctor_name"],
                        session_date=str(row["session_date"]),
                        slot_time=slot_time,
                        reason=reason,
                        appointment_id=str(appt_id),
                    )
                    if log_id:
                        await _mark_sent(db, log_id)
                except Exception as e:
                    logger.error("notify_session_completed cancel send error for %s: %s", appt_id, e)
                    if log_id:
                        await _mark_failed(db, log_id, str(e))

            except Exception as e:
                logger.error("notify_session_completed cancellation email error for %s: %s", appt_id, e)

        logger.info("Session completion emails sent for %s (no_show=%d, cancelled=%d)",
                     session_id, len(no_show_ids), len(cancelled_ids))
    except Exception as e:
        logger.error("notify_session_completed error: %s", e)


async def notify_session_cancelled(db: AsyncSession, session_id: UUID, reason: str = ""):
    """Send cancellation emails to all patients when an entire session is cancelled."""
    try:
        result = await db.execute(
            text("""
                SELECT DISTINCT u.id AS patient_user_id,
                       u.full_name AS patient_name, u.email AS patient_email,
                       u_d.full_name AS doctor_name, s.session_date,
                       a.id AS appointment_id
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

            # Log as pending
            log_id = await _log_pending(
                db,
                user_id=row["patient_user_id"],
                notif_type="SESSION_CANCELLED",
                content=f"Session with Dr. {row['doctor_name']} on {row['session_date']} cancelled. {reason}".strip(),
                appointment_id=row["appointment_id"],
            )

            try:
                await send_session_cancelled_email(
                    to_email=email,
                    patient_name=row["patient_name"],
                    doctor_name=row["doctor_name"],
                    session_date=str(row["session_date"]),
                    reason=reason,
                )
                if log_id:
                    await _mark_sent(db, log_id)
            except Exception as e:
                logger.error("notify_session_cancelled email error for %s: %s", email, e)
                if log_id:
                    await _mark_failed(db, log_id, str(e))

        logger.info("Session cancel notifications sent for %s (%d patients)", session_id, len(rows))
    except Exception as e:
        logger.error("notify_session_cancelled error: %s", e)
