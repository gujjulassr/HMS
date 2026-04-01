"""
Booking Service — the brain of appointment booking and cancellation.

Handles: slot availability, rate limiting, risk score checks,
         priority calculation, waitlist fallback, cancellation penalties,
         and waitlist auto-promotion on cancel.

All business rules live here. Routes are thin wrappers.
"""
from uuid import UUID
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from go.models.user import UserModel
from go.models.patient import Patient, PatientModel
from go.models.doctor import DoctorModel
from go.models.session import Session, SessionModel
from go.models.scheduling_config import ConfigModel
from go.models.patient_relationship import RelationshipModel
from lo.models.appointment import Appointment, AppointmentModel
from lo.models.waitlist import WaitlistModel
from lo.models.cancellation_log import CancellationModel
from lo.models.booking_audit_log import AuditModel
from lo.models.notification_log import NotificationModel


# ─── Priority Calculation ─────────────────────────────────────

def calculate_priority_tier(dob: date) -> str:
    """
    Auto-priority based on age (immutable, set at booking).
    Children (<12) and Seniors (>60) → CRITICAL
    Teens/Elderly (12-18 or 50-60) → HIGH
    Everyone else → NORMAL
    """
    today = date.today()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    if age < 12 or age > 60:
        return "CRITICAL"
    elif age < 18 or age > 50:
        return "HIGH"
    return "NORMAL"


# ─── Risk Score Penalty Calculation ───────────────────────────

def calculate_risk_delta(hours_before: float) -> Decimal:
    """
    Cancellation penalty based on how close to appointment time.
    < 2 hours  → +3.0 (severe)
    < 6 hours  → +2.0 (moderate)
    < 24 hours → +1.0 (mild)
    >= 24 hours → +0.5 (minimal)
    """
    if hours_before < 2:
        return Decimal("3.0")
    elif hours_before < 6:
        return Decimal("2.0")
    elif hours_before < 24:
        return Decimal("1.0")
    return Decimal("0.5")


# ─── Book Appointment ─────────────────────────────────────────

async def book_appointment(
    db: AsyncSession,
    booker_patient: Patient,
    booker_user_id: UUID,
    session_id: UUID,
    slot_number: int,
    beneficiary_patient_id: UUID,
    is_emergency: bool = False,
) -> dict:
    """
    Full booking flow:
    1. Check booker's risk score (blocked if >= 7.0)
    2. Check rate limits (5/day, 15/week)
    3. Verify relationship with beneficiary is approved
    4. Lock session row (SELECT FOR UPDATE)
    5. Check slot availability → get position
    6. If no position → add to waitlist
    7. If position available → create appointment + audit log
    8. Update session booked_count

    Returns dict with status ("booked" or "waitlisted") and details.
    """
    # ── Step 1: Risk score block ──
    if float(booker_patient.risk_score) >= 7.0:
        raise ValueError(
            f"Booking blocked: risk score {booker_patient.risk_score} >= 7.0. "
            "Too many late cancellations. Contact admin to reset."
        )

    # ── Step 2: Rate limits ──
    daily_count = await AppointmentModel.count_booker_today(db, booker_patient.id)
    max_daily = await ConfigModel.get_value(db, "max_bookings_per_day", 5)
    if daily_count >= max_daily:
        raise ValueError(f"Daily booking limit reached ({max_daily}/day)")

    weekly_count = await AppointmentModel.count_booker_week(db, booker_patient.id)
    max_weekly = await ConfigModel.get_value(db, "max_bookings_per_week", 15)
    if weekly_count >= max_weekly:
        raise ValueError(f"Weekly booking limit reached ({max_weekly}/week)")

    # ── Step 3: Verify relationship ──
    if beneficiary_patient_id != booker_patient.id:
        is_approved = await RelationshipModel.check_approved(
            db, booker_patient.id, beneficiary_patient_id
        )
        if not is_approved:
            raise ValueError(
                "No approved relationship with this patient. "
                "Add them as a family member first."
            )

    # ── Step 4: Lock session ──
    session = await SessionModel.get_by_id_for_update(db, session_id)
    if not session:
        raise ValueError("Session not found")
    if session.status != "active":
        raise ValueError(f"Session is {session.status}, not bookable")

    # Validate slot number
    if slot_number < 1 or slot_number > session.total_slots:
        raise ValueError(f"Invalid slot number. Must be 1-{session.total_slots}")

    # ── Lunch break check (13:00-14:00) ──
    # No booking during lunch. Morning sessions can't be extended and
    # afternoon sessions start at 14:00, so no valid slot ever falls here.
    LUNCH_START = 13 * 60  # 1:00 PM
    LUNCH_END = 14 * 60    # 2:00 PM
    slot_start_min = (
        session.start_time.hour * 60 + session.start_time.minute
        + (slot_number - 1) * session.slot_duration_minutes
    )
    slot_end_min = slot_start_min + session.slot_duration_minutes
    if slot_start_min < LUNCH_END and slot_end_min > LUNCH_START:
        raise ValueError(
            f"Slot {slot_number} falls during lunch break (1:00–2:00 PM). Please choose a different slot."
        )

    # ── Step 5: Check slot availability ──
    slot_position = await AppointmentModel.get_next_slot_position(
        db, session_id, slot_number, is_emergency=is_emergency
    )

    # Get beneficiary's DOB for priority calculation
    beneficiary = await PatientModel.get_by_id(db, beneficiary_patient_id)
    if not beneficiary:
        raise ValueError("Beneficiary patient not found")
    priority_tier = calculate_priority_tier(beneficiary.date_of_birth)

    # ── Step 6: No position → waitlist ──
    if slot_position is None:
        # Check if patient is already on the waitlist for this session
        from sqlalchemy import text as _text
        _existing = await db.execute(
            _text("SELECT id, status FROM waitlist WHERE session_id = :sid AND patient_id = :pid LIMIT 1"),
            {"sid": session_id, "pid": beneficiary_patient_id},
        )
        _existing_row = _existing.mappings().first()
        if _existing_row:
            if _existing_row["status"] == "waiting":
                raise ValueError("This patient is already on the waitlist for this session.")
            # Old promoted/cancelled/expired entry — remove so we can re-add
            await db.execute(
                _text("DELETE FROM waitlist WHERE id = :wid"),
                {"wid": _existing_row["id"]},
            )

        waitlist_entry = await WaitlistModel.create(
            db,
            session_id=session_id,
            patient_id=beneficiary_patient_id,
            booked_by_patient_id=booker_patient.id,
            priority_tier=priority_tier,
        )

        # Audit
        await AuditModel.create(
            db,
            action="WAITLISTED",
            performed_by_user_id=booker_user_id,
            patient_id=beneficiary_patient_id,
            metadata={
                "session_id": str(session_id),
                "slot_number": slot_number,
                "waitlist_id": str(waitlist_entry.id),
            },
        )
        await db.commit()

        return {
            "status": "waitlisted",
            "message": f"Slot {slot_number} is full. Added to waitlist with {priority_tier} priority.",
            "appointment": None,
            "waitlist_position": None,  # Could compute position if needed
        }

    # ── Step 7: Create appointment ──
    appointment = await AppointmentModel.create(
        db,
        session_id=session_id,
        patient_id=beneficiary_patient_id,
        booked_by_patient_id=booker_patient.id,
        slot_number=slot_number,
        slot_position=slot_position,
        priority_tier=priority_tier,
        is_emergency=is_emergency,
    )

    # ── Step 8: Update session booked_count ──
    await SessionModel.update_booked_count(db, session_id, delta=1)

    # Audit
    await AuditModel.create(
        db,
        action="BOOKED",
        performed_by_user_id=booker_user_id,
        appointment_id=appointment.id,
        patient_id=beneficiary_patient_id,
        metadata={
            "slot_number": slot_number,
            "slot_position": slot_position,
            "priority_tier": priority_tier,
            "is_emergency": is_emergency,
        },
    )

    await db.commit()

    return {
        "status": "booked",
        "message": f"Appointment booked: slot {slot_number}, position {slot_position}",
        "appointment": appointment,
        "waitlist_position": None,
    }


# ─── Cancel Appointment ──────────────────────────────────────

async def cancel_appointment(
    db: AsyncSession,
    appointment_id: UUID,
    cancelled_by_patient: Patient,
    cancelled_by_user_id: UUID,
    reason: Optional[str] = None,
) -> dict:
    """
    Cancellation flow:
    1. Verify appointment exists and is cancellable
    2. Verify canceller owns the appointment (booker or beneficiary)
    3. Calculate risk penalty based on time until appointment
    4. Cancel appointment → update status
    5. Apply risk penalty to booker
    6. Log cancellation
    7. Decrement session booked_count
    8. Auto-promote next waitlist entry if any
    9. Audit log

    Returns dict with risk_delta and new risk score.
    """
    # ── Step 1: Get appointment ──
    appointment = await AppointmentModel.get_by_id(db, appointment_id)
    if not appointment:
        raise ValueError("Appointment not found")
    if appointment.status not in ("booked", "checked_in"):
        raise ValueError(f"Cannot cancel appointment with status '{appointment.status}'")

    # ── Step 2: Verify ownership ──
    is_owner = (
        cancelled_by_patient.id == appointment.booked_by_patient_id
        or cancelled_by_patient.id == appointment.patient_id
    )
    if not is_owner:
        raise ValueError("You can only cancel your own appointments")

    # ── Step 3: Calculate penalty ──
    # Use the actual slot time, not session start time
    # Slot-0 emergency entries have no scheduled time — skip risk penalty
    session = await SessionModel.get_by_id(db, appointment.session_id)
    if session and appointment.slot_number > 0:
        slot_start_minutes = (
            session.start_time.hour * 60 + session.start_time.minute
            + (appointment.slot_number - 1) * session.slot_duration_minutes
        )
        from datetime import time as dt_time
        slot_time = dt_time(hour=slot_start_minutes // 60, minute=slot_start_minutes % 60)
        appt_datetime = datetime.combine(session.session_date, slot_time)
        hours_before = max(
            (appt_datetime - datetime.now()).total_seconds() / 3600, 0
        )
    else:
        hours_before = 0

    risk_delta = 0.0 if appointment.slot_number == 0 else calculate_risk_delta(hours_before)

    # ── Step 4: Cancel ──
    await AppointmentModel.update_status(db, appointment_id, "cancelled")

    # ── Step 5: Apply risk penalty ──
    updated_patient = await PatientModel.update_risk_score(
        db, appointment.booked_by_patient_id, risk_delta
    )
    new_risk_score = float(updated_patient.risk_score) if updated_patient else 0

    # ── Step 6: Log cancellation ──
    await CancellationModel.create(
        db,
        appointment_id=appointment_id,
        cancelled_by_patient_id=cancelled_by_patient.id,
        risk_delta=risk_delta,
        hours_before_appointment=Decimal(str(round(hours_before, 2))),
        reason=reason,
    )

    # ── Step 7: Decrement session booked_count (skip for slot-0 emergency entries) ──
    if session and appointment.slot_number > 0:
        await SessionModel.update_booked_count(db, session.id, delta=-1)

    # ── Step 8: Auto-promote from waitlist ──
    promoted_msg = ""
    if session:
        next_waiting = await WaitlistModel.get_next_waiting(db, session.id)
        if next_waiting:
            # Find a free slot position in the cancelled slot
            new_position = await AppointmentModel.get_next_slot_position(
                db, session.id, appointment.slot_number
            )
            if new_position:
                # Create appointment for waitlist patient
                promoted_appt = await AppointmentModel.create(
                    db,
                    session_id=session.id,
                    patient_id=next_waiting.patient_id,
                    booked_by_patient_id=next_waiting.booked_by_patient_id,
                    slot_number=appointment.slot_number,
                    slot_position=new_position,
                    priority_tier=next_waiting.priority_tier,
                )
                await WaitlistModel.promote(db, next_waiting.id)
                await SessionModel.update_booked_count(db, session.id, delta=1)
                promoted_msg = " A waitlist patient was auto-promoted to your slot."

    # ── COMMIT critical work first ──
    await db.commit()

    # ── Step 9: Audit (non-critical, after commit) ──
    try:
        await AuditModel.create(
            db,
            action="CANCELLED",
            performed_by_user_id=cancelled_by_user_id,
            appointment_id=appointment_id,
            patient_id=appointment.patient_id,
            metadata={
                "reason": reason,
                "hours_before": round(hours_before, 2),
                "risk_delta": float(risk_delta),
                "new_risk_score": new_risk_score,
            },
        )
        await db.commit()
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass

    # Notification for waitlist promotion (non-critical, after commit)
    if promoted_msg and session:
        try:
            next_waiting_check = await WaitlistModel.get_next_waiting(db, session.id)
            # Use the promoted appointment info we already have
            beneficiary_user = await PatientModel.get_by_id(db, appointment.patient_id)
            if beneficiary_user:
                await NotificationModel.create(
                    db,
                    user_id=beneficiary_user.user_id,
                    type="waitlist_promotion",
                    channel="push",
                    content=f"Waitlist promotion: appointment in slot {appointment.slot_number}.",
                )
                await db.commit()
        except Exception:
            try:
                await db.rollback()
            except Exception:
                pass

    return {
        "status": "cancelled",
        "message": f"Appointment cancelled.{promoted_msg}",
        "risk_delta": float(risk_delta),
        "new_risk_score": new_risk_score,
    }


# ─── Cancel Entire Session (doctor no-show / emergency) ──────

async def cancel_session_appointments(
    db: AsyncSession,
    session_id: UUID,
    performed_by_user_id: UUID,
    reason: str = "Session cancelled by staff",
) -> dict:
    """
    When a doctor can't make it or session is cancelled:
    1. Cancel all booked/checked_in appointments (no risk penalty to patients)
    2. Cancel all waitlist entries
    3. Mark session as cancelled
    4. Best-effort: notify patients, write audit log
    """
    from sqlalchemy import text

    session = await SessionModel.get_by_id(db, session_id)
    if not session:
        raise ValueError("Session not found")
    if session.status not in ("active", "inactive"):
        raise ValueError(f"Session is already {session.status}")

    # ── Block if any patient is currently in_progress ────────
    in_prog = await db.execute(
        text("SELECT COUNT(*) FROM appointments WHERE session_id = :sid AND status = 'in_progress'"),
        {"sid": session_id},
    )
    if in_prog.scalar() > 0:
        raise ValueError("Cannot cancel session — a patient is currently in progress. Finish them first.")

    # ── Step 1a: Mark booked patients as no_show ──────────────
    booked_result = await db.execute(
        text("SELECT id, patient_id FROM appointments WHERE session_id = :sid AND status = 'booked'"),
        {"sid": session_id},
    )
    booked_rows = booked_result.mappings().all()

    no_show_count = 0
    for row in booked_rows:
        await db.execute(
            text("UPDATE appointments SET status = 'no_show' WHERE id = :aid"),
            {"aid": row["id"]},
        )
        # No risk penalty when session is cancelled by staff — not the patient's fault
        no_show_count += 1

    # ── Step 1b: Mark checked_in patients as cancelled ────────
    checked_in_result = await db.execute(
        text("SELECT id, patient_id FROM appointments WHERE session_id = :sid AND status = 'checked_in'"),
        {"sid": session_id},
    )
    checked_in_rows = checked_in_result.mappings().all()

    cancelled_count = 0
    for row in checked_in_rows:
        await db.execute(
            text("UPDATE appointments SET status = 'cancelled' WHERE id = :aid"),
            {"aid": row["id"]},
        )
        cancelled_count += 1

    patient_ids_to_notify = [(r["id"], r["patient_id"]) for r in booked_rows + checked_in_rows]

    # ── Step 2: Cancel waitlist entries ───────────────────────
    waitlist_cancelled = 0
    try:
        wl_result = await db.execute(
            text("SELECT id FROM waitlist WHERE session_id = :sid AND status = 'waiting'"),
            {"sid": session_id},
        )
        for wl_row in wl_result.mappings().all():
            await db.execute(
                text("UPDATE waitlist SET status = 'cancelled' WHERE id = :wid"),
                {"wid": wl_row["id"]},
            )
            waitlist_cancelled += 1
    except Exception:
        pass  # waitlist table might not exist

    # ── Step 3: Mark session cancelled ────────────────────────
    await SessionModel.cancel_session(db, session_id)

    # ── Step 4: Commit core changes ──────────────────────────
    await db.commit()

    # ── Step 5: Best-effort notifications & audit (post-commit) ──
    # These run AFTER commit, so constraint violations won't rollback the cancel.
    for appt_id, patient_id in patient_ids_to_notify:
        try:
            patient = await PatientModel.get_by_id(db, patient_id)
            if patient:
                await NotificationModel.create(
                    db,
                    user_id=patient.user_id,
                    type="cancellation",
                    channel="push",
                    content=f"Your appointment has been cancelled: {reason}. Please rebook.",
                    appointment_id=appt_id,
                )
            await db.commit()
        except Exception:
            try:
                await db.rollback()
            except Exception:
                pass

    try:
        await AuditModel.create(
            db,
            action="SESSION_CANCELLED",
            performed_by_user_id=performed_by_user_id,
            metadata={
                "session_id": str(session_id),
                "reason": reason,
                "no_show_count": no_show_count,
                "appointments_cancelled": cancelled_count,
                "waitlist_cancelled": waitlist_cancelled,
            },
        )
        await db.commit()
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass

    parts = []
    if no_show_count:
        parts.append(f"{no_show_count} no-show")
    if cancelled_count:
        parts.append(f"{cancelled_count} cancelled")
    if waitlist_cancelled:
        parts.append(f"{waitlist_cancelled} waitlist removed")
    summary = ", ".join(parts) if parts else "no pending patients"

    return {
        "status": "session_cancelled",
        "message": f"Session cancelled. {summary}.",
        "appointments_cancelled": cancelled_count,
        "no_show_count": no_show_count,
        "waitlist_cancelled": waitlist_cancelled,
        "no_show_appt_ids": [r["id"] for r in booked_rows],
        "cancelled_appt_ids": [r["id"] for r in checked_in_rows],
    }
