"""
Appointment Routes — book, cancel, reassign, and list appointments.

Patient-facing and staff-facing endpoints. Mounted at: /api/appointments
"""
import logging

from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, get_current_patient, require_role
from go.models.user import User, UserModel
from go.models.patient import Patient, PatientModel
from go.models.doctor import DoctorModel
from go.models.session import SessionModel
from lo.models.appointment import Appointment, AppointmentModel
from lo.models.booking_audit_log import AuditModel
from lo.models.notification_log import NotificationModel
from go.services.booking_service import book_appointment, cancel_appointment
from api.schemas.appointment_schemas import (
    BookAppointmentRequest,
    EmergencyBookRequest,
    CancelAppointmentRequest,
    AppointmentResponse,
    BookingResultResponse,
    CancelResultResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ─── Helper ───────────────────────────────────────────────────

async def _enrich_appointment(db: AsyncSession, appt: Appointment) -> AppointmentResponse:
    """Add doctor name, session info to an appointment response."""
    session = await SessionModel.get_by_id(db, appt.session_id)
    doctor_name = None
    specialization = None
    session_date = None
    start_time = None
    end_time = None
    delay_minutes = 0

    if session:
        session_date = session.session_date
        start_time = session.start_time
        end_time = session.end_time
        delay_minutes = session.delay_minutes
        doctor = await DoctorModel.get_by_id(db, session.doctor_id)
        if doctor:
            doc_user = await UserModel.get_by_id(db, doctor.user_id)
            if doc_user:
                doctor_name = doc_user.full_name
            specialization = doctor.specialization

    # Get patient name
    patient = await PatientModel.get_by_id(db, appt.patient_id)
    patient_name = None
    if patient:
        pat_user = await UserModel.get_by_id(db, patient.user_id)
        if pat_user:
            patient_name = pat_user.full_name

    return AppointmentResponse(
        appointment_id=str(appt.id),
        session_id=str(appt.session_id),
        patient_id=str(appt.patient_id),
        patient_name=patient_name,
        booked_by_patient_id=str(appt.booked_by_patient_id),
        doctor_name=doctor_name,
        specialization=specialization,
        session_date=session_date,
        start_time=start_time,
        end_time=end_time,
        slot_number=appt.slot_number,
        slot_position=appt.slot_position,
        priority_tier=appt.priority_tier,
        visual_priority=appt.visual_priority,
        is_emergency=appt.is_emergency,
        status=appt.status,
        delay_minutes=delay_minutes,
        checked_in_at=appt.checked_in_at,
        completed_at=appt.completed_at,
        notes=appt.notes,
        created_at=appt.created_at,
    )


# ─── POST /book — book an appointment ────────────────────────

@router.post("/book", response_model=BookingResultResponse, status_code=status.HTTP_201_CREATED)
async def book_route(
    body: BookAppointmentRequest,
    user: User = Depends(get_current_user),
    patient: Patient = Depends(get_current_patient),
    db: AsyncSession = Depends(get_db),
):
    """
    Book an appointment in a session slot for yourself or a family member.
    If the slot is full, you're added to the waitlist automatically.
    """
    try:
        result = await book_appointment(
            db=db,
            booker_patient=patient,
            booker_user_id=user.id,
            session_id=UUID(body.session_id),
            slot_number=body.slot_number,
            beneficiary_patient_id=UUID(body.beneficiary_patient_id),
        )

        appt_response = None
        if result["appointment"]:
            appt_response = await _enrich_appointment(db, result["appointment"])

        return BookingResultResponse(
            status=result["status"],
            message=result["message"],
            appointment=appt_response,
            waitlist_position=result["waitlist_position"],
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


# ─── POST /cancel — cancel an appointment ────────────────────

@router.post("/cancel", response_model=CancelResultResponse)
async def cancel_route(
    body: CancelAppointmentRequest,
    user: User = Depends(get_current_user),
    patient: Patient = Depends(get_current_patient),
    db: AsyncSession = Depends(get_db),
):
    """
    Cancel your appointment. Risk penalty applied based on how close
    to the appointment time you cancel. Waitlist patients may be auto-promoted.
    """
    try:
        result = await cancel_appointment(
            db=db,
            appointment_id=UUID(body.appointment_id),
            cancelled_by_patient=patient,
            cancelled_by_user_id=user.id,
            reason=body.reason,
        )

        return CancelResultResponse(
            status=result["status"],
            message=result["message"],
            risk_delta=result["risk_delta"],
            new_risk_score=result["new_risk_score"],
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


# ─── GET /my — list my appointments ──────────────────────────

@router.get("/my", response_model=list[AppointmentResponse])
async def list_my_appointments(
    appt_status: Optional[str] = Query(None, alias="status", description="Filter: booked, checked_in, completed, cancelled, no_show"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    patient: Patient = Depends(get_current_patient),
    db: AsyncSession = Depends(get_db),
):
    """
    List all appointments where you are the patient or the booker.
    Includes delay info so you can see if your doctor is running late.
    """
    appointments = await AppointmentModel.get_by_patient(
        db, patient.id, status=appt_status, limit=limit, offset=offset
    )
    return [await _enrich_appointment(db, appt) for appt in appointments]


# ─── GET /departments — unique specializations for dropdown ──

@router.get("/departments")
async def list_departments(
    user: User = Depends(require_role("nurse", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """Return unique specialization list for filter dropdowns."""
    from sqlalchemy import text as sql_text
    result = await db.execute(
        sql_text("SELECT DISTINCT specialization FROM doctors WHERE specialization IS NOT NULL ORDER BY specialization")
    )
    return [row[0] for row in result.all()]


# ─── GET /board — operations board for staff ─────────────────

@router.get("/board")
async def operations_board(
    date_filter: str = Query(None, alias="date", description="Filter by date YYYY-MM-DD (default: today)"),
    department: str = Query(None, description="Filter by specialization (exact or partial match)"),
    user: User = Depends(require_role("nurse", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """
    Staff operations board: all appointments for a date, grouped by department → doctor.
    Also returns sessions that have zero appointments so nurses see the full picture.
    """
    from sqlalchemy import text as sql_text
    from datetime import date as _d
    from collections import OrderedDict

    target_date = _d.fromisoformat(date_filter) if date_filter else _d.today()

    dept_filter = ""
    params: dict = {"target_date": target_date}
    if department and department != "All":
        dept_filter = "AND d.specialization ILIKE :dept"
        params["dept"] = f"%{department}%"

    # 1) Get all active sessions for the date (even empty ones)
    sess_result = await db.execute(
        sql_text(f"""
            SELECT s.id as session_id, s.session_date, s.start_time, s.end_time,
                   s.slot_duration_minutes, s.total_slots, s.booked_count, s.delay_minutes,
                   d.id as doctor_id, d.specialization,
                   doc_user.full_name as doctor_name
            FROM sessions s
            JOIN doctors d ON d.id = s.doctor_id
            JOIN users doc_user ON doc_user.id = d.user_id
            WHERE s.session_date = :target_date AND s.status = 'active'
              {dept_filter}
            ORDER BY d.specialization, doc_user.full_name, s.start_time
        """),
        params,
    )
    all_sessions = sess_result.mappings().all()

    # Build skeleton with all sessions
    departments: dict = OrderedDict()
    session_map: dict = {}
    for s in all_sessions:
        spec = s["specialization"] or "General"
        doc_key = str(s["doctor_id"])
        sid = str(s["session_id"])
        if spec not in departments:
            departments[spec] = OrderedDict()
        if doc_key not in departments[spec]:
            departments[spec][doc_key] = {
                "doctor_id": doc_key,
                "doctor_name": s["doctor_name"],
                "specialization": spec,
                "session_id": sid,
                "session_date": str(s["session_date"]),
                "start_time": str(s["start_time"]),
                "end_time": str(s["end_time"]),
                "slot_duration_minutes": s["slot_duration_minutes"],
                "total_slots": s["total_slots"],
                "booked_count": s["booked_count"],
                "delay_minutes": s["delay_minutes"] or 0,
                "appointments": [],
            }
        session_map[sid] = (spec, doc_key)

    # 2) Get all appointments for those sessions (re-join to sessions by date)
    appt_result = await db.execute(
        sql_text(f"""
            SELECT a.id as appointment_id, a.session_id, a.patient_id,
                   a.slot_number, a.slot_position, a.priority_tier,
                   a.visual_priority, a.is_emergency, a.status,
                   a.checked_in_at, a.completed_at, a.notes, a.duration_minutes,
                   pat_user.full_name as patient_name, pat_user.phone as patient_phone,
                   p.date_of_birth, p.gender, p.blood_group, p.risk_score, p.abha_id
            FROM appointments a
            JOIN sessions s ON s.id = a.session_id
            JOIN doctors d ON d.id = s.doctor_id
            JOIN patients p ON p.id = a.patient_id
            JOIN users pat_user ON pat_user.id = p.user_id
            WHERE s.session_date = :target_date AND s.status = 'active'
              {dept_filter}
            ORDER BY a.slot_number, a.slot_position
        """),
        params,
    )
    appt_rows = appt_result.mappings().all()

    status_counts: dict = {}
    for row in appt_rows:
        sid = str(row["session_id"])
        if sid not in session_map:
            continue
        spec, doc_key = session_map[sid]

        s = row["status"]
        status_counts[s] = status_counts.get(s, 0) + 1

        age = None
        if row["date_of_birth"]:
            today = _d.today()
            dob = row["date_of_birth"]
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

        departments[spec][doc_key]["appointments"].append({
            "appointment_id": str(row["appointment_id"]),
            "session_id": sid,
            "patient_id": str(row["patient_id"]),
            "patient_name": row["patient_name"],
            "patient_phone": row["patient_phone"],
            "patient_age": age,
            "patient_gender": row["gender"],
            "patient_blood_group": row["blood_group"],
            "patient_risk_score": float(row["risk_score"]) if row["risk_score"] is not None else 0,
            "slot_number": row["slot_number"],
            "slot_position": row["slot_position"],
            "priority_tier": row["priority_tier"],
            "visual_priority": row["visual_priority"],
            "is_emergency": row["is_emergency"],
            "status": row["status"],
            "checked_in_at": str(row["checked_in_at"]) if row["checked_in_at"] else None,
            "completed_at": str(row["completed_at"]) if row["completed_at"] else None,
            "notes": row["notes"],
            "duration_minutes": row["duration_minutes"],
        })

    board = []
    for spec, doctors_map in departments.items():
        board.append({"department": spec, "doctors": list(doctors_map.values())})

    return {
        "date": str(target_date),
        "total_appointments": len(appt_rows),
        "status_summary": status_counts,
        "departments": board,
    }


# ─── GET /{appointment_id} — get one appointment ─────────────

@router.get("/{appointment_id}", response_model=AppointmentResponse)
async def get_appointment(
    appointment_id: str,
    user: User = Depends(get_current_user),
    patient: Patient = Depends(get_current_patient),
    db: AsyncSession = Depends(get_db),
):
    """Get details of a specific appointment. Shows real-time delay info."""
    appt = await AppointmentModel.get_by_id(db, UUID(appointment_id))
    if not appt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Appointment not found",
        )

    # Verify ownership
    is_owner = (
        patient.id == appt.booked_by_patient_id
        or patient.id == appt.patient_id
    )
    if not is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own appointments",
        )

    return await _enrich_appointment(db, appt)


# ─── POST /emergency — staff-only emergency override ─────────

@router.post("/emergency", response_model=BookingResultResponse, status_code=status.HTTP_201_CREATED)
async def emergency_book_route(
    body: EmergencyBookRequest,
    user: User = Depends(require_role("nurse", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """
    Staff-only: force-book a patient into slot position 3 (emergency override).

    Bypasses:
    - Rate limiting (not the patient's choice)
    - Risk score check (emergency overrides everything)
    - Waitlist (goes straight to position 3)

    Does NOT bypass:
    - Slot must exist
    - Position 3 must be free
    - Patient must exist

    Only nurse and admin can do this. Doctor tells staff, staff does the booking.
    """
    session_id = UUID(body.session_id)
    patient_id = UUID(body.patient_id)

    # Validate session
    session = await SessionModel.get_by_id_for_update(db, session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Session is {session.status}")
    if body.slot_number < 1 or body.slot_number > session.total_slots:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid slot. Must be 1-{session.total_slots}",
        )

    # Validate patient exists
    patient = await PatientModel.get_by_id(db, patient_id)
    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")

    # Check position 3 is available for this slot
    slot_position = await AppointmentModel.get_next_slot_position(
        db, session_id, body.slot_number, is_emergency=True
    )
    if slot_position is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="All 3 positions (including emergency) are taken for this slot",
        )

    # Calculate priority from patient age
    from go.services.booking_service import calculate_priority_tier
    priority_tier = calculate_priority_tier(patient.date_of_birth)

    # Create the emergency appointment
    appointment = await AppointmentModel.create(
        db,
        session_id=session_id,
        patient_id=patient_id,
        booked_by_patient_id=patient_id,  # self-booked via staff
        slot_number=body.slot_number,
        slot_position=slot_position,
        priority_tier=priority_tier,
        is_emergency=True,
    )

    # Update session booked count
    await SessionModel.update_booked_count(db, session_id, delta=1)

    # Notify the patient
    await NotificationModel.create(
        db,
        user_id=patient.user_id,
        type="EMERGENCY_BOOKED",
        channel="in_app",
        content=f"Emergency appointment booked for you in slot {body.slot_number}. Reason: {body.reason}",
        appointment_id=appointment.id,
    )

    await db.commit()

    # Audit in separate transaction — failure won't undo the booking
    try:
        await AuditModel.create(
            db, action="book", performed_by_user_id=user.id,
            appointment_id=appointment.id, patient_id=patient_id,
            metadata={"slot_number": body.slot_number, "slot_position": slot_position,
                       "reason": body.reason, "booked_by_staff": str(user.id)},
        )
        await db.commit()
    except Exception:
        try: await db.rollback()
        except Exception: pass

    appt_response = await _enrich_appointment(db, appointment)

    return BookingResultResponse(
        status="booked",
        message=f"Emergency appointment booked: slot {body.slot_number}, position {slot_position}. Reason: {body.reason}",
        appointment=appt_response,
        waitlist_position=None,
    )


# ─── POST /undo-cancel — reverse a patient cancellation ─────

@router.post("/undo-cancel")
async def undo_cancel_route(
    body: CancelAppointmentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Undo a cancellation: move appointment from cancelled → booked.
    The risk penalty that was applied is reversed (subtracted back).
    """
    appt = await AppointmentModel.get_by_id(db, UUID(body.appointment_id))
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status != "cancelled":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot undo cancel: status is '{appt.status}', expected 'cancelled'",
        )

    # Restore to booked
    await AppointmentModel.update_status(db, appt.id, "booked")

    # Reverse risk penalty: find the cancel audit to know delta, or use flat -5
    risk_reversed = 5  # default reversal
    try:
        patient = await PatientModel.get_by_id(db, appt.patient_id)
        if patient:
            new_score = max(0, patient.risk_score - risk_reversed)
            await PatientModel.update_risk_score(db, patient.id, new_score)
    except Exception as e:
        logger.warning(f"Risk reversal failed: {e}")

    await db.commit()

    # Audit
    try:
        await AuditModel.create(
            db, action="cancel", performed_by_user_id=user.id,
            appointment_id=appt.id, patient_id=appt.patient_id,
            metadata={"sub_action": "undo_cancel", "risk_reversed": risk_reversed},
        )
        await db.commit()
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass

    return {
        "status": "undone",
        "message": "Cancellation reversed. Appointment is back to booked.",
        "appointment_id": str(appt.id),
        "risk_reversed": risk_reversed,
    }


# ─── POST /reassign — move appointment to another doctor ─────

@router.post("/reassign")
async def reassign_appointment(
    request: Request,
    user: User = Depends(require_role("nurse", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """
    Reassign a booked/checked_in appointment to a different session or time slot.
    Supports same-doctor time changes and cross-doctor reassignments.
    """
    from sqlalchemy import text as sql_text

    # Parse request body
    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    try:
        appt_id = UUID(str(body["appointment_id"]))
        target_session_id = UUID(str(body["target_session_id"]))
        target_slot = int(body["target_slot_number"])
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"Missing or invalid field: {e}")

    logger.info(f"Reassign requested: appt={appt_id} -> session={target_session_id}, slot={target_slot}")

    try:
        # Validate appointment exists and is reassignable
        appt = await AppointmentModel.get_by_id(db, appt_id)
        if not appt:
            raise HTTPException(status_code=404, detail="Appointment not found")
        if appt.status not in ("booked", "checked_in"):
            raise HTTPException(status_code=400, detail=f"Cannot reassign: status is '{appt.status}'")

        # Validate target session is active and slot is in range
        target_session = await SessionModel.get_by_id(db, target_session_id)
        if not target_session:
            raise HTTPException(status_code=404, detail="Target session not found")
        if target_session.status != "active":
            raise HTTPException(status_code=400, detail=f"Target session is '{target_session.status}', must be 'active'")
        if target_slot < 1 or target_slot > target_session.total_slots:
            raise HTTPException(status_code=400, detail=f"Slot {target_slot} invalid. Range: 1-{target_session.total_slots}")

        # Check slot availability (position 1 or 2; 3 reserved for emergency)
        slot_pos = await AppointmentModel.get_next_slot_position(db, target_session_id, target_slot)
        if slot_pos is None:
            raise HTTPException(status_code=409, detail="Target slot is full")

        old_session_id = appt.session_id

        # Move appointment to new session/slot — pass native Python types (asyncpg requirement)
        await db.execute(
            sql_text(
                "UPDATE appointments "
                "SET session_id = :new_sid, slot_number = :new_slot, slot_position = :new_pos "
                "WHERE id = :id"
            ),
            {"new_sid": target_session_id, "new_slot": target_slot, "new_pos": slot_pos, "id": appt_id},
        )

        # Adjust booked counts if moving between different sessions
        if old_session_id != target_session_id:
            await db.execute(
                sql_text("UPDATE sessions SET booked_count = booked_count - 1 WHERE id = :id"),
                {"id": old_session_id},
            )
            await db.execute(
                sql_text("UPDATE sessions SET booked_count = booked_count + 1 WHERE id = :id"),
                {"id": target_session_id},
            )

        await db.commit()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Reassign failed: {type(e).__name__}: {e}", exc_info=True)
        try:
            await db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Reassign error: {type(e).__name__}: {e}")

    # ── Best-effort audit ──
    try:
        await AuditModel.create(
            db, action="book", performed_by_user_id=user.id,
            appointment_id=appt_id, patient_id=appt.patient_id,
            metadata={"sub_action": "reassign",
                       "from_session": str(old_session_id),
                       "to_session": str(target_session_id),
                       "new_slot": target_slot},
        )
        await db.commit()
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass

    # ── Get doctor name (best-effort) ──
    doc_name = "another doctor"
    try:
        doctor = await DoctorModel.get_by_id(db, target_session.doctor_id)
        if doctor:
            doc_user = await UserModel.get_by_id(db, doctor.user_id)
            if doc_user:
                doc_name = doc_user.full_name
    except Exception:
        pass

    logger.info(f"Reassign complete: appt {appt_id} -> {doc_name}, slot {target_slot}")
    return {
        "status": "reassigned",
        "message": f"Appointment reassigned to {doc_name}, slot {target_slot}.",
        "appointment_id": str(appt_id),
        "new_session_id": str(target_session_id),
        "new_slot_number": target_slot,
        "new_slot_position": slot_pos,
    }


# ─── POST /staff-book — nurse books on behalf of patient ─────

@router.post("/staff-book")
async def staff_book(
    body: dict,
    user: User = Depends(require_role("nurse", "admin", "doctor")),
    db: AsyncSession = Depends(get_db),
):
    """
    Nurse books an appointment for a patient.
    Bypasses rate limiting but NOT slot capacity.
    Patient must already exist in the system.
    """
    session_id = UUID(body["session_id"])
    patient_id = UUID(body["patient_id"])
    slot_number = body["slot_number"]

    # Validate session
    session = await SessionModel.get_by_id_for_update(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "active":
        raise HTTPException(status_code=400, detail=f"Session is {session.status}")
    if slot_number < 1 or slot_number > session.total_slots:
        raise HTTPException(status_code=400, detail=f"Invalid slot. Must be 1-{session.total_slots}")

    # Validate patient
    patient = await PatientModel.get_by_id(db, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Check slot availability
    slot_pos = await AppointmentModel.get_next_slot_position(db, session_id, slot_number)
    if slot_pos is None:
        raise HTTPException(status_code=409, detail="Slot is full. Try another slot or use emergency booking.")

    # Priority from age
    from go.services.booking_service import calculate_priority_tier
    priority_tier = calculate_priority_tier(patient.date_of_birth)

    # Create appointment
    appointment = await AppointmentModel.create(
        db,
        session_id=session_id,
        patient_id=patient_id,
        booked_by_patient_id=patient_id,
        slot_number=slot_number,
        slot_position=slot_pos,
        priority_tier=priority_tier,
    )

    await SessionModel.update_booked_count(db, session_id, delta=1)

    # Notify
    try:
        await NotificationModel.create(
            db, user_id=patient.user_id, type="BOOKED_BY_STAFF", channel="in_app",
            content=f"An appointment has been booked for you in slot {slot_number} by staff.",
            appointment_id=appointment.id,
        )
    except Exception:
        pass

    await db.commit()

    # Audit
    try:
        await AuditModel.create(
            db, action="book", performed_by_user_id=user.id,
            appointment_id=appointment.id, patient_id=patient_id,
            metadata={"sub_action": "staff_book", "slot_number": slot_number,
                       "slot_position": slot_pos, "booked_by_staff": str(user.id)},
        )
        await db.commit()
    except Exception:
        try: await db.rollback()
        except Exception: pass

    # Get doctor name
    doctor = await DoctorModel.get_by_id(db, session.doctor_id)
    doc_name = "Doctor"
    if doctor:
        doc_user = await UserModel.get_by_id(db, doctor.user_id)
        if doc_user:
            doc_name = doc_user.full_name

    pat_user = await UserModel.get_by_id(db, patient.user_id)
    pat_name = pat_user.full_name if pat_user else "Patient"

    return {
        "status": "booked",
        "message": f"{pat_name} booked with {doc_name} — Slot {slot_number}, Position {slot_pos}.",
        "appointment_id": str(appointment.id),
        "session_id": str(session_id),
        "slot_number": slot_number,
        "slot_position": slot_pos,
    }


# ─── POST /staff-register-book — nurse registers patient + books ────
@router.post("/staff-register-book")
async def staff_register_book(
    body: dict,
    user: User = Depends(require_role("nurse", "admin", "doctor")),
    db: AsyncSession = Depends(get_db),
):
    """
    Nurse registers a new patient and immediately books an appointment.
    Creates user → patient → appointment in one step.
    No email/password required — staff creates the record.
    """
    from datetime import date as _date_type
    import uuid as _uuid

    # Required fields
    full_name = body.get("full_name", "").strip()
    if not full_name or len(full_name) < 2:
        raise HTTPException(400, "Full name is required (min 2 chars)")

    session_id = UUID(body["session_id"])
    slot_number = body.get("slot_number", 1)

    # Optional fields — body values may be None so guard .strip()
    def _s(val):
        return val.strip() if isinstance(val, str) else None

    phone = _s(body.get("phone")) or None
    gender = body.get("gender") or "other"
    dob_str = body.get("date_of_birth") or ""
    abha_id = _s(body.get("abha_id")) or None
    blood_group = _s(body.get("blood_group")) or None
    address = _s(body.get("address")) or None
    emergency_contact = _s(body.get("emergency_contact")) or None
    emergency_phone = _s(body.get("emergency_phone")) or None

    try:
        dob = _date_type.fromisoformat(dob_str) if dob_str else _date_type(2000, 1, 1)
    except Exception:
        dob = _date_type(2000, 1, 1)

    # Create a unique placeholder email (patient won't login)
    placeholder_email = f"walkin_{_uuid.uuid4().hex[:8]}@dpms.local"

    # Validate session
    session = await SessionModel.get_by_id_for_update(db, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.status != "active":
        raise HTTPException(400, f"Session is {session.status}")

    # 1. Create user (users table has: email, full_name, role, password_hash, phone)
    new_user = await UserModel.create(
        db,
        email=placeholder_email,
        full_name=full_name,
        role="patient",
        password_hash="WALKIN_NO_LOGIN",
        phone=phone,
    )

    # 2. Create patient record (patients table has: user_id, dob, gender, abha, blood, emergency, address)
    new_patient = await PatientModel.create(
        db,
        user_id=new_user.id,
        date_of_birth=dob,
        gender=gender,
        abha_id=abha_id,
        blood_group=blood_group,
        emergency_contact_name=emergency_contact,
        emergency_contact_phone=emergency_phone,
        address=address,
    )

    # 3. Create self-relationship
    from go.models.patient_relationship import RelationshipModel
    try:
        await RelationshipModel.create(
            db,
            booker_patient_id=new_patient.id,
            beneficiary_patient_id=new_patient.id,
            relationship_type="self",
        )
    except Exception:
        pass  # non-critical

    # 4. Book appointment — get correct slot_position within the slot
    slot_pos = await AppointmentModel.get_next_slot_position(db, session_id, slot_number)
    if slot_pos is None:
        raise HTTPException(409, "Slot is full. Try another slot number.")

    appointment = await AppointmentModel.create(
        db,
        session_id=session_id,
        patient_id=new_patient.id,
        booked_by_patient_id=new_patient.id,
        slot_number=slot_number,
        slot_position=slot_pos,
        priority_tier="NORMAL",
        is_emergency=False,
    )
    session.booked_count += 1
    await db.commit()

    # Audit
    try:
        await AuditModel.create(
            db,
            action="staff_register_book",
            performed_by_user_id=user.id,
            appointment_id=appointment.id,
            patient_id=new_patient.id,
            metadata={"patient_name": full_name, "slot_number": slot_number, "registered_by": str(user.id)},
        )
        await db.commit()
    except Exception:
        try: await db.rollback()
        except Exception: pass

    return {
        "status": "registered_and_booked",
        "message": f"{full_name} registered and booked — Slot {slot_number}, Position {slot_pos}.",
        "patient_id": str(new_patient.id),
        "appointment_id": str(appointment.id),
    }
