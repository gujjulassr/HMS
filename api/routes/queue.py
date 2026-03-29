"""
Queue Routes — in-clinic patient flow management.

Flow: booked → checked_in → in_progress → completed | no_show
Mounted at: /api/queue
"""
from uuid import UUID
from datetime import datetime, time as dt_time
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import require_role
from go.models.user import User, UserModel
from go.models.patient import PatientModel
from go.models.doctor import DoctorModel
from go.models.session import Session, SessionModel
from lo.models.appointment import Appointment, AppointmentModel, _safe_appointment
from lo.models.booking_audit_log import AuditModel
from lo.models.notification_log import NotificationModel
from api.schemas.queue_schemas import (
    PatientCheckinRequest,
    SetDurationRequest,
    CallNextRequest,
    CompleteAppointmentRequest,
    EscalatePriorityRequest,
    MarkNoShowRequest,
    MarkSingleNoShowRequest,
    QueueEntry,
    QueueResponse,
    CheckinResponse,
    CompleteResponse,
    NoShowResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ─── Helpers ──────────────────────────────────────────────────

def _time_to_minutes(t: dt_time) -> int:
    return t.hour * 60 + t.minute

def _minutes_to_time(minutes: int) -> dt_time:
    return dt_time(hour=min(minutes // 60, 23), minute=minutes % 60)


async def _try_audit(db, **kwargs):
    """Best-effort audit. Commits its own transaction. Never raises."""
    try:
        await AuditModel.create(db, **kwargs)
        await db.commit()
    except Exception as e:
        logger.warning(f"Audit failed: {e}")
        try:
            await db.rollback()
        except Exception:
            pass


async def _build_queue_entry(
    db: AsyncSession, appt: Appointment, position: int,
    session: Session | None = None,
) -> QueueEntry:
    patient = await PatientModel.get_by_id(db, appt.patient_id)
    patient_name = None
    patient_age = None
    patient_gender = None
    patient_blood_group = None
    patient_phone = None
    patient_address = None
    patient_emergency_contact = None
    patient_emergency_phone = None
    patient_risk_score = None
    patient_abha_id = None
    if patient:
        pat_user = await UserModel.get_by_id(db, patient.user_id)
        if pat_user:
            patient_name = pat_user.full_name
            patient_phone = pat_user.phone
        else:
            # Fallback: try without is_active filter
            from sqlalchemy import text as _sql
            _row = await db.execute(
                _sql("SELECT full_name, phone FROM users WHERE id = :uid"),
                {"uid": patient.user_id},
            )
            _u = _row.mappings().first()
            if _u:
                patient_name = _u["full_name"]
                patient_phone = _u["phone"]
        patient_gender = patient.gender
        patient_blood_group = patient.blood_group
        patient_address = patient.address
        patient_emergency_contact = patient.emergency_contact_name
        patient_emergency_phone = patient.emergency_contact_phone
        patient_risk_score = float(patient.risk_score) if patient.risk_score is not None else None
        patient_abha_id = patient.abha_id
        if patient.date_of_birth:
            from datetime import date as _date
            today = _date.today()
            dob = patient.date_of_birth
            patient_age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    original_slot_time = None
    estimated_time = None
    estimated_wait_minutes = None

    if session:
        start_min = _time_to_minutes(session.start_time)
        slot_min = start_min + (appt.slot_number - 1) * session.slot_duration_minutes
        original_slot_time = _minutes_to_time(slot_min)
        estimated_min = slot_min + session.delay_minutes
        estimated_time = _minutes_to_time(estimated_min)
        estimated_wait_minutes = max(estimated_min - start_min, 0)

    return QueueEntry(
        appointment_id=str(appt.id),
        patient_id=str(appt.patient_id),
        patient_name=patient_name,
        patient_age=patient_age,
        patient_gender=patient_gender,
        patient_blood_group=patient_blood_group,
        patient_phone=patient_phone,
        patient_address=patient_address,
        patient_emergency_contact=patient_emergency_contact,
        patient_emergency_phone=patient_emergency_phone,
        patient_risk_score=patient_risk_score,
        patient_abha_id=patient_abha_id,
        slot_number=appt.slot_number,
        slot_position=appt.slot_position,
        priority_tier=appt.priority_tier,
        visual_priority=appt.visual_priority,
        is_emergency=appt.is_emergency,
        status=appt.status,
        checked_in_at=appt.checked_in_at,
        completed_at=getattr(appt, 'completed_at', None),
        queue_position=position,
        original_slot_time=original_slot_time,
        estimated_time=estimated_time,
        estimated_wait_minutes=estimated_wait_minutes,
        duration_minutes=getattr(appt, 'duration_minutes', None),
    )


# ─── GET /{session_id} — view the queue ──────────────────────

@router.get("/{session_id}", response_model=QueueResponse)
async def get_queue(
    session_id: str,
    user: User = Depends(require_role("doctor", "nurse", "admin")),
    db: AsyncSession = Depends(get_db),
):
    session = await SessionModel.get_by_id(db, UUID(session_id))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    doctor_name = None
    doctor = await DoctorModel.get_by_id(db, session.doctor_id)
    if doctor:
        doc_user = await UserModel.get_by_id(db, doctor.user_id)
        if doc_user:
            doctor_name = doc_user.full_name

    # Checked-in (the queue)
    queue_appts = await AppointmentModel.get_queue(db, UUID(session_id))
    queue_entries = []
    for i, appt in enumerate(queue_appts, start=1):
        entry = await _build_queue_entry(db, appt, position=i, session=session)
        queue_entries.append(entry)

    # Booked (not-arrived)
    from sqlalchemy import text as sql_text
    booked_result = await db.execute(
        sql_text("SELECT * FROM appointments WHERE session_id = :sid AND status = 'booked' ORDER BY slot_number, slot_position"),
        {"sid": UUID(session_id)},
    )
    for row in booked_result.mappings().all():
        appt = _safe_appointment(row)
        entry = await _build_queue_entry(db, appt, position=0, session=session)
        queue_entries.append(entry)

    # Completed appointments (for undo)
    completed_result = await db.execute(
        sql_text("SELECT * FROM appointments WHERE session_id = :sid AND status = 'completed' ORDER BY completed_at DESC"),
        {"sid": UUID(session_id)},
    )
    for row in completed_result.mappings().all():
        appt = _safe_appointment(row)
        entry = await _build_queue_entry(db, appt, position=0, session=session)
        queue_entries.append(entry)

    completed_count = len([e for e in queue_entries if e.status == "completed"])

    # No-show appointments (for undo)
    noshow_result = await db.execute(
        sql_text("SELECT * FROM appointments WHERE session_id = :sid AND status = 'no_show' ORDER BY slot_number"),
        {"sid": UUID(session_id)},
    )
    for row in noshow_result.mappings().all():
        appt = _safe_appointment(row)
        entry = await _build_queue_entry(db, appt, position=0, session=session)
        queue_entries.append(entry)

    # Current patient (in_progress)
    ip_result = await db.execute(
        sql_text("SELECT * FROM appointments WHERE session_id = :sid AND status = 'in_progress'"),
        {"sid": UUID(session_id)},
    )
    ip_rows = ip_result.mappings().all()
    current = None
    if ip_rows:
        current = await _build_queue_entry(db, _safe_appointment(ip_rows[0]), position=0, session=session)

    checked_in_count = len([e for e in queue_entries if e.status == "checked_in"])

    return QueueResponse(
        session_id=session_id,
        doctor_name=doctor_name,
        session_date=str(session.session_date),
        session_status=session.status,
        session_start_time=str(session.start_time),
        session_end_time=str(session.end_time),
        delay_minutes=session.delay_minutes,
        slot_duration_minutes=session.slot_duration_minutes,
        total_slots=session.total_slots,
        booked_count=session.booked_count,
        max_patients_per_slot=session.max_patients_per_slot,
        total_in_queue=checked_in_count,
        completed_count=completed_count,
        current_patient=current,
        queue=queue_entries,
    )


# ─── POST /checkin ────────────────────────────────────────────

@router.post("/checkin", response_model=CheckinResponse)
async def checkin_patient(
    body: PatientCheckinRequest,
    user: User = Depends(require_role("nurse", "admin")),
    db: AsyncSession = Depends(get_db),
):
    appt = await AppointmentModel.get_by_id(db, UUID(body.appointment_id))
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status != "booked":
        raise HTTPException(status_code=400, detail=f"Cannot check in: status is '{appt.status}'")

    extra = {
        "visual_priority": body.visual_priority,
        "checked_in_at": datetime.now(),
        "checked_in_by": user.id,
    }
    if body.priority_tier:
        extra["priority_tier"] = body.priority_tier
    if body.is_emergency:
        extra["is_emergency"] = True
        if not body.priority_tier or body.priority_tier == "NORMAL":
            extra["priority_tier"] = "CRITICAL"
    if body.duration_minutes is not None:
        extra["duration_minutes"] = body.duration_minutes

    try:
        await AppointmentModel.update_status(db, appt.id, "checked_in", **extra)
    except Exception:
        extra.pop("duration_minutes", None)
        await AppointmentModel.update_status(db, appt.id, "checked_in", **extra)

    queue = await AppointmentModel.get_queue(db, appt.session_id)
    position = next((i for i, q in enumerate(queue, 1) if q.id == appt.id), len(queue))

    # COMMIT the checkin first — so it persists no matter what
    await db.commit()

    # Then try audit in a fresh transaction
    await _try_audit(
        db, action="check_in", performed_by_user_id=user.id,
        appointment_id=appt.id, patient_id=appt.patient_id,
        metadata={"visual_priority": body.visual_priority, "queue_position": position},
    )

    return CheckinResponse(
        status="checked_in",
        message=f"Patient checked in. Queue position: {position}",
        queue_position=position,
        appointment_id=str(appt.id),
    )


# ─── POST /undo-checkin — nurse reverses a wrong check-in ────

@router.post("/undo-checkin")
async def undo_checkin(
    body: PatientCheckinRequest,
    user: User = Depends(require_role("nurse", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """Undo a check-in: move patient back from checked_in → booked."""
    appt = await AppointmentModel.get_by_id(db, UUID(body.appointment_id))
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status != "checked_in":
        raise HTTPException(status_code=400, detail=f"Cannot undo: status is '{appt.status}', expected 'checked_in'")

    await AppointmentModel.update_status(
        db, appt.id, "booked",
        visual_priority=5,
        checked_in_at=None,
        checked_in_by=None,
    )
    await db.commit()

    await _try_audit(
        db, action="check_in", performed_by_user_id=user.id,
        appointment_id=appt.id, patient_id=appt.patient_id,
        metadata={"sub_action": "undo_checkin"},
    )

    return {"status": "undone", "message": "Check-in reversed. Patient moved back to Not Arrived.",
            "appointment_id": str(appt.id)}


# ─── POST /undo-send — reverse calling patient to doctor ─────

@router.post("/undo-send")
async def undo_send(
    body: CallNextRequest,
    user: User = Depends(require_role("doctor", "nurse", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """Undo send-to-doctor: move patient back from in_progress → checked_in."""
    from sqlalchemy import text as sql_text
    result = await db.execute(
        sql_text("SELECT * FROM appointments WHERE session_id = :sid AND status = 'in_progress'"),
        {"sid": UUID(body.session_id)},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=400, detail="No patient currently with doctor.")

    appt = _safe_appointment(row)
    await AppointmentModel.update_status(db, appt.id, "checked_in")
    await db.commit()

    await _try_audit(
        db, action="check_in", performed_by_user_id=user.id,
        appointment_id=appt.id, patient_id=appt.patient_id,
        metadata={"sub_action": "undo_send"},
    )

    patient = await PatientModel.get_by_id(db, appt.patient_id)
    name = "Patient"
    if patient:
        pu = await UserModel.get_by_id(db, patient.user_id)
        if pu:
            name = pu.full_name

    return {"status": "undone", "message": f"{name} sent back to waiting queue.", "appointment_id": str(appt.id)}


# ─── POST /undo-complete — reverse a completion ──────────────

@router.post("/undo-complete")
async def undo_complete(
    body: CompleteAppointmentRequest,
    user: User = Depends(require_role("doctor", "nurse", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """Undo complete: move patient back from completed → in_progress."""
    appt = await AppointmentModel.get_by_id(db, UUID(body.appointment_id))
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status != "completed":
        raise HTTPException(status_code=400, detail=f"Cannot undo: status is '{appt.status}', expected 'completed'")

    await AppointmentModel.update_status(
        db, appt.id, "in_progress",
        completed_at=None,
    )
    await db.commit()

    await _try_audit(
        db, action="complete", performed_by_user_id=user.id,
        appointment_id=appt.id, patient_id=appt.patient_id,
        metadata={"sub_action": "undo_complete"},
    )

    return {"status": "undone", "message": "Completion reversed. Patient back with doctor.",
            "appointment_id": str(appt.id)}


# ─── POST /undo-noshow — reverse a no-show mark ─────────────

@router.post("/undo-noshow")
async def undo_noshow(
    body: PatientCheckinRequest,
    user: User = Depends(require_role("nurse", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """Undo no-show: move patient back from no_show → booked."""
    appt = await AppointmentModel.get_by_id(db, UUID(body.appointment_id))
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status != "no_show":
        raise HTTPException(status_code=400, detail=f"Cannot undo: status is '{appt.status}', expected 'no_show'")

    await AppointmentModel.update_status(db, appt.id, "booked", visual_priority=5)
    await db.commit()

    await _try_audit(
        db, action="no_show", performed_by_user_id=user.id,
        appointment_id=appt.id, patient_id=appt.patient_id,
        metadata={"sub_action": "undo_noshow"},
    )

    return {"status": "undone", "message": "No-show reversed. Patient back to Not Arrived.",
            "appointment_id": str(appt.id)}


# ─── POST /set-duration ──────────────────────────────────────

@router.post("/set-duration")
async def set_duration(
    body: SetDurationRequest,
    user: User = Depends(require_role("nurse", "admin")),
    db: AsyncSession = Depends(get_db),
):
    appt = await AppointmentModel.get_by_id(db, UUID(body.appointment_id))
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")

    try:
        await AppointmentModel.update_status(db, appt.id, appt.status, duration_minutes=body.duration_minutes)
        await db.commit()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not set duration (run migration 016). {e}")

    return {"status": "updated", "message": f"Duration set to {body.duration_minutes} min.",
            "appointment_id": str(appt.id), "duration_minutes": body.duration_minutes}


# ─── POST /call-patient — call a SPECIFIC patient in ─────────

@router.post("/call-patient")
async def call_specific_patient(
    body: CompleteAppointmentRequest,  # reuse: has appointment_id
    user: User = Depends(require_role("doctor", "nurse", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """Call a specific checked-in patient to the doctor. Only one patient at a time."""
    appt = await AppointmentModel.get_by_id(db, UUID(body.appointment_id))
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status != "checked_in":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot call: status is '{appt.status}', expected 'checked_in'",
        )

    # BLOCK if another patient is already with the doctor
    from sqlalchemy import text as _txt
    row = (await db.execute(
        _txt("SELECT id FROM appointments WHERE session_id = :sid AND status = 'in_progress' LIMIT 1"),
        {"sid": str(appt.session_id)},
    )).first()
    if row:
        raise HTTPException(
            status_code=400,
            detail="Another patient is already with the doctor. Complete that visit first.",
        )

    # Set this patient to in_progress
    await db.execute(
        _txt("UPDATE appointments SET status = 'in_progress' WHERE id = :aid AND status = 'checked_in'"),
        {"aid": str(appt.id)},
    )
    await db.commit()

    await _try_audit(
        db, action="call_patient", performed_by_user_id=user.id,
        appointment_id=appt.id, patient_id=appt.patient_id,
        metadata={"session_id": str(appt.session_id)},
    )

    return {"status": "called", "message": "Patient called in.", "appointment_id": str(appt.id)}


# ─── POST /next ───────────────────────────────────────────────

@router.post("/next", response_model=CompleteResponse)
async def call_next_patient(
    body: CallNextRequest,
    user: User = Depends(require_role("doctor", "nurse", "admin")),
    db: AsyncSession = Depends(get_db),
):
    session = await SessionModel.get_by_id(db, UUID(body.session_id))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    next_appt = await AppointmentModel.get_next_in_queue(db, UUID(body.session_id))
    if not next_appt:
        return CompleteResponse(status="queue_empty", message="No more patients in the queue.", next_patient=None)

    await AppointmentModel.update_status(db, next_appt.id, "in_progress")
    next_entry = await _build_queue_entry(db, next_appt, position=1)

    # COMMIT main work first
    await db.commit()

    await _try_audit(
        db, action="check_in", performed_by_user_id=user.id,
        appointment_id=next_appt.id, patient_id=next_appt.patient_id,
        metadata={"session_id": body.session_id, "sub_action": "called_next"},
    )

    return CompleteResponse(status="called", message=f"Calling {next_entry.patient_name or 'next patient'}.", next_patient=next_entry)


# ─── POST /escalate — change patient priority ────────────────

@router.post("/escalate")
async def escalate_priority(
    body: EscalatePriorityRequest,
    user: User = Depends(require_role("doctor", "nurse", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """Doctor or staff changes a patient's priority tier, visual priority, or emergency flag."""
    appt = await AppointmentModel.get_by_id(db, UUID(body.appointment_id))
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status in ("completed", "cancelled", "no_show"):
        raise HTTPException(status_code=400, detail=f"Cannot escalate: status is '{appt.status}'")

    updates = {}
    if body.priority_tier is not None:
        if body.priority_tier not in ("NORMAL", "HIGH", "CRITICAL"):
            raise HTTPException(status_code=400, detail="priority_tier must be NORMAL, HIGH, or CRITICAL")
        updates["priority_tier"] = body.priority_tier
    if body.visual_priority is not None:
        updates["visual_priority"] = body.visual_priority
    if body.is_emergency is not None:
        updates["is_emergency"] = body.is_emergency

    if not updates:
        raise HTTPException(status_code=400, detail="No priority fields provided")

    updated = await AppointmentModel.update_status(db, appt.id, appt.status, **updates)
    await db.commit()

    await _try_audit(
        db, action="escalate_priority", performed_by_user_id=user.id,
        appointment_id=appt.id, patient_id=appt.patient_id,
        metadata={"updates": {k: str(v) for k, v in updates.items()}, "reason": body.reason},
    )

    return {
        "status": "updated",
        "message": f"Priority updated for appointment. {body.reason}",
        "appointment_id": str(appt.id),
        "priority_tier": updated.priority_tier if updated else appt.priority_tier,
        "visual_priority": updated.visual_priority if updated else appt.visual_priority,
        "is_emergency": updated.is_emergency if updated else appt.is_emergency,
    }


# ─── POST /complete ──────────────────────────────────────────

@router.post("/complete", response_model=CompleteResponse)
async def complete_appointment(
    body: CompleteAppointmentRequest,
    user: User = Depends(require_role("doctor", "nurse", "admin")),
    db: AsyncSession = Depends(get_db),
):
    appt = await AppointmentModel.get_by_id(db, UUID(body.appointment_id))
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status != "in_progress":
        raise HTTPException(status_code=400, detail=f"Cannot complete: status is '{appt.status}', expected 'in_progress'")

    await AppointmentModel.update_status(db, appt.id, "completed", completed_at=datetime.now(), notes=body.notes)

    next_appt = await AppointmentModel.get_next_in_queue(db, appt.session_id)
    next_entry = None
    if next_appt:
        next_entry = await _build_queue_entry(db, next_appt, position=1)

    # COMMIT main work first
    await db.commit()

    await _try_audit(
        db, action="complete", performed_by_user_id=user.id,
        appointment_id=appt.id, patient_id=appt.patient_id,
        metadata={"notes": body.notes},
    )

    msg = "Appointment completed."
    if next_entry:
        msg += f" Next: {next_entry.patient_name or 'next patient'}."
    else:
        msg += " No more patients in queue."

    return CompleteResponse(status="completed", message=msg, next_patient=next_entry)


# ─── POST /no-shows ──────────────────────────────────────────

@router.post("/no-shows", response_model=NoShowResponse)
async def mark_no_shows(
    body: MarkNoShowRequest,
    user: User = Depends(require_role("nurse", "admin")),
    db: AsyncSession = Depends(get_db),
):
    session = await SessionModel.get_by_id(db, UUID(body.session_id))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    count = await AppointmentModel.mark_no_shows(db, UUID(body.session_id))

    # COMMIT main work first
    await db.commit()

    await _try_audit(
        db, action="no_show", performed_by_user_id=user.id,
        metadata={"session_id": body.session_id, "no_show_count": count},
    )

    return NoShowResponse(status="done", message=f"{count} appointments marked as no_show.", no_show_count=count)


# ─── POST /no-show-single — mark ONE patient as no-show ─────

@router.post("/no-show-single")
async def mark_single_no_show(
    body: MarkSingleNoShowRequest,
    user: User = Depends(require_role("doctor", "nurse", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """Mark a single booked or checked-in patient as no-show."""
    appt = await AppointmentModel.get_by_id(db, UUID(body.appointment_id))
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status not in ("booked", "checked_in"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot mark no-show: status is '{appt.status}', expected 'booked' or 'checked_in'",
        )

    await AppointmentModel.update_status(db, appt.id, "no_show")
    await db.commit()

    await _try_audit(
        db, action="no_show", performed_by_user_id=user.id,
        appointment_id=appt.id, patient_id=appt.patient_id,
        metadata={"reason": body.reason or "Marked as no-show"},
    )

    return {"status": "no_show", "message": f"Patient marked as no-show.", "appointment_id": str(appt.id)}
