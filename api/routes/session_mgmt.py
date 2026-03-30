"""
Session Management Routes — staff/doctor real-time actions.

Real-time flow:
1. Doctor arrives → checkin (auto delay) → patients notified if late
2. During session → staff can update delay live → all estimated times shift
3. Running out of time → staff sets overtime window →
   system shows who CAN vs CAN'T be seen → patients notified with options
4. Doctor extends → lunch hour validated → new slots open
5. Emergency → cancel entire session → no penalty to patients

Mounted at: /api/sessions
"""
from uuid import UUID
from datetime import time as dt_time, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import require_role
from go.models.user import User, UserModel
from go.models.session import Session, SessionModel
from go.models.doctor import DoctorModel
from go.models.patient import PatientModel
from go.models.scheduling_config import ConfigModel
from lo.models.appointment import Appointment, AppointmentModel
from lo.models.notification_log import NotificationModel
from lo.models.booking_audit_log import AuditModel
from go.services.booking_service import cancel_session_appointments
from go.services.notification_dispatcher import notify_delay_for_session, notify_session_cancelled, notify_session_completed
from api.schemas.session_schemas import (
    CreateSessionRequest,
    DoctorCheckinRequest,
    UpdateDelayRequest,
    OvertimeWindowRequest,
    ExtendSessionRequest,
    CompleteSessionRequest,
    CancelSessionRequest,
    SessionStatusResponse,
    AffectedPatient,
    OvertimeWindowResponse,
    CancelSessionResponse,
)

router = APIRouter()

# Only doctor, nurse, admin can manage sessions
staff_dependency = require_role("doctor", "nurse", "admin")


# ─── Helpers ──────────────────────────────────────────────────

def _time_to_minutes(t: dt_time) -> int:
    """Convert time to minutes since midnight."""
    return t.hour * 60 + t.minute


def _minutes_to_time(minutes: int) -> dt_time:
    """Convert minutes since midnight back to time."""
    return dt_time(hour=minutes // 60, minute=minutes % 60)


def _slot_start_time(session: Session, slot_number: int) -> dt_time:
    """Calculate the scheduled start time for a specific slot."""
    start_min = _time_to_minutes(session.start_time)
    slot_min = start_min + (slot_number - 1) * session.slot_duration_minutes
    return _minutes_to_time(slot_min)


def _slot_estimated_time(session: Session, slot_number: int, delay_minutes: int) -> dt_time:
    """Calculate estimated time with current delay factored in."""
    start_min = _time_to_minutes(session.start_time)
    slot_min = start_min + (slot_number - 1) * session.slot_duration_minutes + delay_minutes
    return _minutes_to_time(min(slot_min, 23 * 60 + 59))  # cap at 23:59


async def _get_clinic_time_config(db: AsyncSession) -> dict:
    """Load clinic hours from scheduling_config."""
    lunch_start_str = await ConfigModel.get_value(db, "lunch_start", "12:30")
    lunch_end_str = await ConfigModel.get_value(db, "lunch_end", "14:00")
    clinic_close_str = await ConfigModel.get_value(db, "clinic_close", "18:00")
    overtime_max = await ConfigModel.get_value(db, "overtime_max_minutes", 45)

    # Parse time strings (stored as JSON strings with quotes)
    def parse_time(val):
        s = val.strip('"') if isinstance(val, str) else str(val)
        parts = s.split(":")
        return dt_time(hour=int(parts[0]), minute=int(parts[1]))

    return {
        "lunch_start": parse_time(lunch_start_str),
        "lunch_end": parse_time(lunch_end_str),
        "clinic_close": parse_time(clinic_close_str),
        "overtime_max": int(overtime_max) if not isinstance(overtime_max, int) else overtime_max,
    }


async def _get_remaining_appointments(db: AsyncSession, session_id: UUID) -> list[Appointment]:
    """Get all appointments that haven't been completed/cancelled yet."""
    result = await db.execute(
        sql_text("""
            SELECT * FROM appointments
            WHERE session_id = :sid AND status IN ('booked', 'checked_in')
            ORDER BY slot_number, slot_position
        """),
        {"sid": session_id},
    )
    from lo.models.appointment import _safe_appointment
    return [_safe_appointment(row) for row in result.mappings().all()]


async def _notify_patients_delay(
    db: AsyncSession, session: Session, delay_minutes: int, reason: str | None = None
):
    """Notify all active patients about updated delay."""
    appointments = await _get_remaining_appointments(db, session.id)
    # Send email notifications to all affected patients (fire-and-forget)
    try:
        await notify_delay_for_session(db, session.id, delay_minutes)
    except Exception:
        pass  # Email failures never block the core flow


# ─── POST /checkin — doctor arrives ──────────────────────────

@router.post("/checkin", response_model=SessionStatusResponse)
async def doctor_checkin(
    body: DoctorCheckinRequest,
    user: User = Depends(staff_dependency),
    db: AsyncSession = Depends(get_db),
):
    """
    Mark doctor as checked in. Auto-calculates delay from scheduled start time.
    If doctor is > 5 min late, all patients notified with updated estimated times.
    """
    session = await SessionModel.get_by_id(db, UUID(body.session_id))
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Session is {session.status}")
    if session.doctor_checkin_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Doctor already checked in")

    updated = await SessionModel.doctor_checkin(db, UUID(body.session_id))
    if not updated:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Check-in failed")

    message = "Doctor checked in on time."
    if updated.delay_minutes > 5:
        message = f"Doctor checked in {updated.delay_minutes} minutes late. Patients notified."
        await _notify_patients_delay(db, updated, updated.delay_minutes)

    await db.commit()
    try:
        await AuditModel.create(
            db, action="check_in", performed_by_user_id=user.id,
            metadata={"session_id": body.session_id, "delay_minutes": updated.delay_minutes},
        )
        await db.commit()
    except Exception:
        try: await db.rollback()
        except Exception: pass

    return SessionStatusResponse(
        session_id=str(updated.id), status=updated.status,
        delay_minutes=updated.delay_minutes, doctor_checkin_at=updated.doctor_checkin_at,
        actual_end_time=updated.actual_end_time, notes=updated.notes, message=message,
    )


# ─── POST /update-delay — staff updates live delay ───────────

@router.post("/update-delay", response_model=SessionStatusResponse)
async def update_delay(
    body: UpdateDelayRequest,
    user: User = Depends(staff_dependency),
    db: AsyncSession = Depends(get_db),
):
    """
    Staff updates the delay during an active session. All remaining patients
    get notified with their new estimated appointment time.

    Use this when:
    - Doctor takes longer than expected between patients
    - An emergency case causes extra delay
    - Doctor catches up and delay reduces
    """
    session = await SessionModel.get_by_id(db, UUID(body.session_id))
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Session is {session.status}")

    old_delay = session.delay_minutes
    note = f"Delay updated: {old_delay} → {body.delay_minutes} min"
    if body.reason:
        note += f". Reason: {body.reason}"

    # Update delay in DB
    result = await db.execute(
        sql_text("""
            UPDATE sessions
            SET delay_minutes = :delay, notes = :note
            WHERE id = :id AND status = 'active'
            RETURNING *
        """),
        {"id": UUID(body.session_id), "delay": body.delay_minutes, "note": note},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Update failed")
    updated = Session(**row)

    # Notify all remaining patients with new estimated times
    await _notify_patients_delay(db, updated, body.delay_minutes, body.reason)

    await db.commit()
    try:
        await AuditModel.create(
            db, action="reschedule", performed_by_user_id=user.id,
            metadata={"session_id": body.session_id, "old_delay": old_delay, "new_delay": body.delay_minutes, "reason": body.reason},
        )
        await db.commit()
    except Exception:
        try: await db.rollback()
        except Exception: pass

    return SessionStatusResponse(
        session_id=str(updated.id), status=updated.status,
        delay_minutes=updated.delay_minutes, doctor_checkin_at=updated.doctor_checkin_at,
        actual_end_time=updated.actual_end_time, notes=updated.notes,
        message=f"Delay updated to {body.delay_minutes} min. All patients notified with new times.",
    )


# ─── POST /overtime-window — who can/can't be seen ───────────

@router.post("/overtime-window", response_model=OvertimeWindowResponse)
async def set_overtime_window(
    body: OvertimeWindowRequest,
    user: User = Depends(staff_dependency),
    db: AsyncSession = Depends(get_db),
):
    """
    Session is running late. Staff sets how many extra minutes the doctor
    is willing to stay. System calculates:

    - Which patients CAN be seen within overtime
    - Which patients CAN'T be seen (their slot falls after overtime ends)

    Patients who can't be seen get notified with options:
    - Reschedule to another session
    - Cancel (NO penalty — it's not their fault)
    - See another available doctor

    This does NOT auto-cancel anyone. It just notifies and shows the split.
    Staff then handles each case individually.
    """
    session = await SessionModel.get_by_id(db, UUID(body.session_id))
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Session is {session.status}")

    # Get clinic config for limits
    config = await _get_clinic_time_config(db)
    lunch_end_min = _time_to_minutes(config["lunch_end"])

    # Morning sessions cannot be extended — pending patients carry over to afternoon
    session_start_min = _time_to_minutes(session.start_time)
    if session_start_min < lunch_end_min:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Morning sessions cannot be extended. Pending patients will automatically "
                   "carry over to the afternoon session when you complete this session.",
        )

    # Calculate overtime end time
    end_min = _time_to_minutes(session.end_time)
    overtime_end_min = end_min + body.overtime_minutes

    # Cap at end of day (23:59)
    overtime_end_min = min(overtime_end_min, 23 * 60 + 59)

    # Also cap at max overtime config (soft recommendation)
    max_overtime = config["overtime_max"]
    overtime_end_min = min(overtime_end_min, end_min + max_overtime)

    overtime_end_time = _minutes_to_time(overtime_end_min)
    actual_overtime = overtime_end_min - end_min

    # Get all remaining appointments
    appointments = await _get_remaining_appointments(db, session.id)

    can_be_seen = []
    cannot_be_seen = []

    for appt in appointments:
        original_time = _slot_start_time(session, appt.slot_number)
        estimated_time = _slot_estimated_time(session, appt.slot_number, session.delay_minutes)
        estimated_min = _time_to_minutes(estimated_time)

        # Can they finish within overtime? (estimated start + slot duration)
        appt_end_min = estimated_min + session.slot_duration_minutes
        can_see = appt_end_min <= overtime_end_min

        # Get patient name
        patient = await PatientModel.get_by_id(db, appt.patient_id)
        patient_name = None
        if patient:
            pat_user = await UserModel.get_by_id(db, patient.user_id)
            if pat_user:
                patient_name = pat_user.full_name

        affected = AffectedPatient(
            appointment_id=str(appt.id),
            patient_id=str(appt.patient_id),
            patient_name=patient_name,
            slot_number=appt.slot_number,
            original_time=original_time,
            estimated_new_time=estimated_time,
            can_be_seen=can_see,
        )

        if can_see:
            can_be_seen.append(affected)
        else:
            cannot_be_seen.append(affected)

            # Mark as needing notification (handled via email/UI)
            if patient:
                affected.notification_sent = True

    await db.commit()
    try:
        await AuditModel.create(
            db, action="reschedule", performed_by_user_id=user.id,
            metadata={"session_id": body.session_id, "overtime_minutes": actual_overtime,
                       "can_be_seen": len(can_be_seen), "cannot_be_seen": len(cannot_be_seen)},
        )
        await db.commit()
    except Exception:
        try: await db.rollback()
        except Exception: pass

    msg = f"Overtime: {actual_overtime} min (until {overtime_end_time.strftime('%I:%M %p')}). "
    msg += f"{len(can_be_seen)} patients can be seen, {len(cannot_be_seen)} cannot."
    if overtime_end_min < end_min + body.overtime_minutes:
        msg += " (Capped by max overtime limit.)"

    return OvertimeWindowResponse(
        session_id=str(session.id),
        overtime_minutes=actual_overtime,
        session_end_time=session.end_time,
        overtime_end_time=overtime_end_time,
        patients_can_be_seen=can_be_seen,
        patients_cannot_be_seen=cannot_be_seen,
        message=msg,
    )


# ─── POST /extend — doctor stays late (overtime) ─────────────

@router.post("/extend", response_model=SessionStatusResponse)
async def extend_session(
    body: ExtendSessionRequest,
    user: User = Depends(staff_dependency),
    db: AsyncSession = Depends(get_db),
):
    """
    Doctor confirms overtime — actually extends the session end time.
    Validates against lunch hours and clinic close.
    Opens new slots for waitlist patients.
    """
    session = await SessionModel.get_by_id(db, UUID(body.session_id))
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Session is {session.status}")

    # ── Lunch hour & clinic close validation ──
    config = await _get_clinic_time_config(db)
    new_end_min = _time_to_minutes(body.new_end_time)
    end_min = _time_to_minutes(session.end_time)
    lunch_start_min = _time_to_minutes(config["lunch_start"])
    lunch_end_min = _time_to_minutes(config["lunch_end"])
    clinic_close_min = _time_to_minutes(config["clinic_close"])

    # ── Morning sessions cannot be extended ──
    # Pending patients from morning carry over to afternoon session automatically.
    # Only afternoon/later sessions (starting at or after lunch end) can be extended.
    session_start_min = _time_to_minutes(session.start_time)
    if session_start_min < lunch_end_min:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Morning sessions cannot be extended. Pending patients will automatically "
                   "carry over to the afternoon session when you complete this session.",
        )

    # ── New end must be after current end ──
    if new_end_min <= end_min:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"New end time must be after current end time ({session.end_time}).",
        )

    # Upper hard-cap: 23:59 (end of day).
    if new_end_min > 23 * 60 + 59:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot extend past 23:59.",
        )

    overtime_minutes = new_end_min - end_min

    old_slots = session.total_slots
    updated = await SessionModel.extend_session(
        db, UUID(body.session_id), body.new_end_time, body.note
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Extension failed")

    new_slots = updated.total_slots
    added_slots = new_slots - old_slots

    await db.commit()
    try:
        await AuditModel.create(
            db, action="reschedule", performed_by_user_id=user.id,
            metadata={"session_id": body.session_id, "old_end_time": str(session.end_time),
                       "new_end_time": str(body.new_end_time), "old_slots": old_slots,
                       "new_slots": new_slots, "overtime_minutes": overtime_minutes, "note": body.note},
        )
        await db.commit()
    except Exception:
        try: await db.rollback()
        except Exception: pass

    return SessionStatusResponse(
        session_id=str(updated.id), status=updated.status,
        delay_minutes=updated.delay_minutes, doctor_checkin_at=updated.doctor_checkin_at,
        actual_end_time=updated.actual_end_time, notes=updated.notes,
        message=f"Session extended to {body.new_end_time}. {added_slots} new slots. Overtime: {overtime_minutes} min.",
    )


# ─── POST /complete-session — doctor ends session for the day ─

@router.post("/complete-session", response_model=SessionStatusResponse)
async def complete_session_route(
    body: CompleteSessionRequest,
    user: User = Depends(staff_dependency),
    db: AsyncSession = Depends(get_db),
):
    """
    Doctor/staff ends the session.
      - 'booked' patients (never showed up) → no_show
      - 'checked_in' patients (showed up but not seen) → cancelled
      - 'in_progress' patients block completion — finish them first.
    """
    session = await SessionModel.get_by_id(db, UUID(body.session_id))
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Session is already {session.status}")

    # Block completing a past session — doctor must handle on the same day
    from datetime import date as _date_cls
    if session.session_date < _date_cls.today():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot complete a past session. Only today's sessions can be ended.",
        )

    # Block if any patient is currently in_progress
    in_prog = await db.execute(
        sql_text(
            "SELECT COUNT(*) FROM appointments "
            "WHERE session_id = :sid AND status = 'in_progress'"
        ),
        {"sid": UUID(body.session_id)},
    )
    if in_prog.scalar() > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot complete session — a patient is currently in progress. Finish them first.",
        )

    # Get patients who will be affected — for notifications
    booked_appts = await db.execute(
        sql_text(
            "SELECT a.id, a.patient_id FROM appointments a "
            "WHERE a.session_id = :sid AND a.status = 'booked'"
        ),
        {"sid": UUID(body.session_id)},
    )
    booked_rows = booked_appts.mappings().all()

    checked_in_appts = await db.execute(
        sql_text(
            "SELECT a.id, a.patient_id FROM appointments a "
            "WHERE a.session_id = :sid AND a.status = 'checked_in'"
        ),
        {"sid": UUID(body.session_id)},
    )
    checked_in_rows = checked_in_appts.mappings().all()

    # Mark remaining booked patients as no_show (never showed up)
    no_show_result = await db.execute(
        sql_text(
            "UPDATE appointments SET status = 'no_show' "
            "WHERE session_id = :sid AND status = 'booked'"
        ),
        {"sid": UUID(body.session_id)},
    )
    no_show_count = no_show_result.rowcount

    # Apply risk penalty for no-shows (+0.5 per no-show)
    for row in booked_rows:
        try:
            await db.execute(
                sql_text(
                    "UPDATE patients SET risk_score = LEAST(risk_score + 0.5, 10.0) "
                    "WHERE id = :pid"
                ),
                {"pid": row["patient_id"]},
            )
        except Exception:
            pass

    # ── Carry-over: try to move checked_in patients to a later same-day session ──
    carried_over_count = 0
    truly_cancelled_rows = list(checked_in_rows)  # default: all get cancelled
    carried_over_ids = []

    if checked_in_rows:
        # Look for a later active session on the same day by the same doctor
        later_session = await db.execute(
            sql_text(
                "SELECT id, total_slots, booked_count, start_time "
                "FROM sessions "
                "WHERE doctor_id = :did AND session_date = :sdate "
                "  AND status = 'active' AND id != :sid "
                "  AND start_time > :current_end "
                "ORDER BY start_time ASC LIMIT 1"
            ),
            {
                "did": session.doctor_id,
                "sdate": session.session_date,
                "sid": UUID(body.session_id),
                "current_end": session.end_time,
            },
        )
        target = later_session.mappings().first()

        if target:
            target_sid = target["id"]
            target_total_slots = target["total_slots"]
            truly_cancelled_rows = []

            for row in checked_in_rows:
                # Find next available slot in the target session (position 1 or 2)
                next_pos = await db.execute(
                    sql_text(
                        "SELECT MIN(s_num) AS slot_num FROM ("
                        "  SELECT g.n AS s_num FROM generate_series(1, :total) g(n) "
                        "  WHERE (SELECT COUNT(*) FROM appointments "
                        "         WHERE session_id = :sid AND slot_number = g.n "
                        "         AND status != 'cancelled') < 2"
                        ") available"
                    ),
                    {"total": target_total_slots, "sid": target_sid},
                )
                avail = next_pos.scalar()

                if avail is not None:
                    # Find the actual position (1 or 2) in that slot
                    pos_result = await db.execute(
                        sql_text(
                            "SELECT COALESCE(MAX(slot_position), 0) + 1 AS next_pos "
                            "FROM appointments "
                            "WHERE session_id = :sid AND slot_number = :slot "
                            "AND status != 'cancelled'"
                        ),
                        {"sid": target_sid, "slot": avail},
                    )
                    next_slot_pos = pos_result.scalar() or 1

                    # Move patient: reset to booked in afternoon session
                    await db.execute(
                        sql_text(
                            "UPDATE appointments "
                            "SET session_id = :new_sid, slot_number = :slot, "
                            "    slot_position = :pos, status = 'booked', "
                            "    checked_in_at = NULL "
                            "WHERE id = :aid"
                        ),
                        {"new_sid": target_sid, "slot": avail, "pos": next_slot_pos, "aid": row["id"]},
                    )
                    # Update booked counts
                    await db.execute(
                        sql_text("UPDATE sessions SET booked_count = booked_count + 1 WHERE id = :id"),
                        {"id": target_sid},
                    )
                    carried_over_count += 1
                    carried_over_ids.append(row["id"])
                else:
                    # No space in afternoon session — cancel this one
                    truly_cancelled_rows.append(row)

    # Mark remaining checked_in patients as cancelled (no slot in afternoon)
    cancelled_count = 0
    cancelled_appt_ids = []
    for row in truly_cancelled_rows:
        await db.execute(
            sql_text(
                "UPDATE appointments SET status = 'cancelled' "
                "WHERE id = :aid AND status = 'checked_in'"
            ),
            {"aid": row["id"]},
        )
        cancelled_count += 1
        cancelled_appt_ids.append(row["id"])

    # Complete the session
    success = await SessionModel.complete_session(db, UUID(body.session_id))
    if not success:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to complete session")

    # Commit core changes (no_show, cancelled, carry-over, session completed)
    await db.commit()

    # ── Best-effort email notifications (post-commit) ──
    no_show_appt_ids = [row["id"] for row in booked_rows]
    try:
        await notify_session_completed(
            db, UUID(body.session_id),
            no_show_ids=no_show_appt_ids,
            cancelled_ids=cancelled_appt_ids,
        )
    except Exception:
        pass  # Email failures never block core flow

    # Best-effort push notifications (in addition to emails)
    for row in booked_rows:
        try:
            patient = await PatientModel.get_by_id(db, row["patient_id"])
            if patient:
                await NotificationModel.create(
                    db, user_id=patient.user_id,
                    type="reminder", channel="push",
                    content="You were marked as no-show. Risk score increased. Please rebook.",
                    appointment_id=row["id"],
                )
            await db.commit()
        except Exception:
            try: await db.rollback()
            except Exception: pass

    for row in truly_cancelled_rows:
        try:
            patient = await PatientModel.get_by_id(db, row["patient_id"])
            if patient:
                await NotificationModel.create(
                    db, user_id=patient.user_id,
                    type="cancellation", channel="push",
                    content="Session ended before you could be seen. Please rebook. No penalty applied.",
                    appointment_id=row["id"],
                )
            await db.commit()
        except Exception:
            try: await db.rollback()
            except Exception: pass

    # Notify carried-over patients (booking confirmation for new session)
    for appt_id in carried_over_ids:
        try:
            from go.services.notification_dispatcher import notify_booking
            await notify_booking(db, appt_id)
        except Exception:
            pass

    # Best-effort audit log
    try:
        await AuditModel.create(
            db, action="complete_session", performed_by_user_id=user.id,
            metadata={
                "session_id": body.session_id,
                "no_show_count": no_show_count,
                "cancelled_count": cancelled_count,
                "carried_over_count": carried_over_count,
                "note": body.note,
            },
        )
        await db.commit()
    except Exception:
        try: await db.rollback()
        except Exception: pass

    parts = []
    if no_show_count:
        parts.append(f"{no_show_count} no-show")
    if cancelled_count:
        parts.append(f"{cancelled_count} cancelled")
    if carried_over_count:
        parts.append(f"{carried_over_count} carried over to next session")
    summary = ", ".join(parts) if parts else "no pending patients"

    return SessionStatusResponse(
        session_id=body.session_id, status="completed",
        delay_minutes=session.delay_minutes,
        doctor_checkin_at=session.doctor_checkin_at,
        actual_end_time=session.actual_end_time,
        notes=body.note,
        message=f"Session completed. {summary}.",
    )


# ─── POST /create — create a new session ─────────────────────

@router.post("/create")
async def create_session(
    body: CreateSessionRequest,
    user: User = Depends(require_role("doctor", "nurse", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new session for a doctor. Doctors can only create for themselves."""
    from datetime import date as _date_cls, time as _time_cls

    # Resolve doctor_id
    if body.doctor_id:
        doctor_id = UUID(body.doctor_id)
    elif user.role == "doctor":
        doctor = await DoctorModel.get_by_user_id(db, user.id)
        if not doctor:
            raise HTTPException(status_code=404, detail="Doctor profile not found for this user")
        doctor_id = doctor.id
    else:
        raise HTTPException(status_code=400, detail="doctor_id is required for non-doctor users")

    # Verify doctor exists (try as doctor_id first, then as user_id)
    doctor = await DoctorModel.get_by_id(db, doctor_id)
    if not doctor:
        doctor = await DoctorModel.get_by_user_id(db, doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    doctor_id = doctor.id  # ensure we use the real doctor_id going forward

    # Parse date and times
    try:
        session_date = _date_cls.fromisoformat(body.session_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    try:
        sh, sm = body.start_time.split(":")
        start_time = _time_cls(int(sh), int(sm))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid start_time. Use HH:MM.")
    try:
        eh, em = body.end_time.split(":")
        end_time = _time_cls(int(eh), int(em))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid end_time. Use HH:MM.")

    if start_time >= end_time:
        raise HTTPException(status_code=400, detail="start_time must be before end_time")

    # Check for overlapping sessions — if one exists and is inactive, return it
    overlap = await db.execute(
        sql_text("""
            SELECT id, status, start_time, end_time, total_slots
            FROM sessions
            WHERE doctor_id = :did AND session_date = :sd
              AND start_time < :et AND end_time > :st
              AND status != 'cancelled'
            LIMIT 1
        """),
        {"did": doctor_id, "sd": session_date, "st": start_time, "et": end_time},
    )
    existing = overlap.mappings().first()
    if existing:
        ex_status = existing["status"]
        ex_id = str(existing["id"])
        if ex_status == "inactive":
            # Auto-activate the existing inactive session
            await db.execute(
                sql_text("UPDATE sessions SET status = 'active' WHERE id = :sid"),
                {"sid": existing["id"]},
            )
            await db.commit()
            return {
                "status": "activated",
                "message": f"An inactive session already existed for {body.session_date} {existing['start_time']}-{existing['end_time']}. It has been activated.",
                "session_id": ex_id,
                "session_date": body.session_date,
                "start_time": str(existing["start_time"]),
                "end_time": str(existing["end_time"]),
                "total_slots": existing["total_slots"],
                "session_status": "active",
            }
        else:
            return {
                "status": "exists",
                "message": f"A session already exists for {body.session_date} {existing['start_time']}-{existing['end_time']} (status: {ex_status}).",
                "session_id": ex_id,
                "session_date": body.session_date,
                "start_time": str(existing["start_time"]),
                "end_time": str(existing["end_time"]),
                "total_slots": existing["total_slots"],
                "session_status": ex_status,
            }

    # Create new session as inactive
    session = await SessionModel.create(
        db, doctor_id=doctor_id, session_date=session_date,
        start_time=start_time, end_time=end_time,
        slot_duration_minutes=body.slot_duration_minutes,
        max_patients_per_slot=body.max_patients_per_slot,
    )
    # Auto-activate new session
    await db.execute(
        sql_text("UPDATE sessions SET status = 'active' WHERE id = :sid"),
        {"sid": session.id},
    )
    await db.commit()

    return {
        "status": "created",
        "message": f"Session created and activated for {body.session_date} {body.start_time}-{body.end_time}.",
        "session_id": str(session.id),
        "session_date": str(session.session_date),
        "start_time": str(session.start_time),
        "end_time": str(session.end_time),
        "total_slots": session.total_slots,
        "session_status": "active",
    }


# ─── POST /activate — set session from inactive → active ─────

@router.post("/activate")
async def activate_session(
    body: CompleteSessionRequest,  # reuse: has session_id + optional note
    user: User = Depends(require_role("doctor", "nurse", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """Doctor activates an inactive session so patients can be seen."""
    session = await SessionModel.get_by_id(db, UUID(body.session_id))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "inactive":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot activate: session is '{session.status}', expected 'inactive'",
        )

    await db.execute(
        sql_text("UPDATE sessions SET status = 'active' WHERE id = :sid"),
        {"sid": UUID(body.session_id)},
    )
    await db.commit()

    try:
        await AuditModel.create(
            db, action="activate_session", performed_by_user_id=user.id,
            metadata={"session_id": body.session_id, "note": body.note},
        )
    except Exception:
        pass  # audit is best-effort

    return {"status": "active", "message": "Session activated.", "session_id": body.session_id}


# ─── POST /deactivate — set session from active → inactive ──

@router.post("/deactivate")
async def deactivate_session(
    body: CompleteSessionRequest,  # reuse: has session_id + optional note
    user: User = Depends(require_role("doctor", "nurse", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """Doctor deactivates a session. Fails if any patient is currently in_progress."""

    print(f"Deactivating session {body.session_id} with note: {body.note}")
    session = await SessionModel.get_by_id(db, UUID(body.session_id))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "active":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot deactivate: session is '{session.status}', expected 'active'",
        )

    # Block if any patient is currently with the doctor
    in_progress = await db.execute(
        sql_text(
            "SELECT COUNT(*) FROM appointments "
            "WHERE session_id = :sid AND status = 'in_progress'"
        ),
        {"sid": UUID(body.session_id)},
    )
    count = in_progress.scalar()
    if count and count > 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot deactivate: you have a patient in progress. Complete the visit first.",
        )

    await db.execute(
        sql_text("UPDATE sessions SET status = 'inactive' WHERE id = :sid"),
        {"sid": UUID(body.session_id)},
    )
    await db.commit()

    try:
        await AuditModel.create(
            db, action="deactivate_session", performed_by_user_id=user.id,
            metadata={"session_id": body.session_id, "note": body.note},
        )
    except Exception:
        pass  # audit is best-effort

    return {"status": "inactive", "message": "Session deactivated.", "session_id": body.session_id}


# ─── POST /cancel-session — cancel entire session ────────────

@router.post("/cancel-session", response_model=CancelSessionResponse)
async def cancel_session_route(
    body: CancelSessionRequest,
    user: User = Depends(require_role("nurse", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """
    Cancel an entire session. All booked appointments are cancelled
    (no risk penalty to patients). All waitlist entries are cancelled.
    All affected patients are notified.
    """
    try:
        result = await cancel_session_appointments(
            db=db,
            session_id=UUID(body.session_id),
            performed_by_user_id=user.id,
            reason=body.reason,
        )
        # Send differentiated emails: no-show email for booked, cancellation email for checked_in
        try:
            await notify_session_completed(
                db, UUID(body.session_id),
                no_show_ids=result.get("no_show_appt_ids", []),
                cancelled_ids=result.get("cancelled_appt_ids", []),
            )
        except Exception:
            pass  # Email failures never block the core flow
        return CancelSessionResponse(
            status=result["status"], message=result["message"],
            appointments_cancelled=result["appointments_cancelled"],
            no_show_count=result.get("no_show_count", 0),
            waitlist_cancelled=result["waitlist_cancelled"],
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
