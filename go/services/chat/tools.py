"""Chat tools — function_tool definitions for all roles.

Tools are organized by capability and grouped into tool sets.
Each role gets a specific combination of these tool groups.
"""

import logging
from datetime import date

from agents import function_tool, RunContextWrapper

from go.services.chat._client import (
    _api, _j, _parse_hhmm, _fmt_hhmm, _next_available_slot_min, _resolve_preferred_time_to_slot,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
#  TOOLS — Information & Discovery
# ═══════════════════════════════════════════════════════════════

@function_tool
async def list_departments(ctx: RunContextWrapper) -> str:
    """List all hospital departments/specializations."""
    return _j(await _api("GET", "/appointments/departments", ctx.context["token"]))


@function_tool
async def list_doctors(ctx: RunContextWrapper, specialization: str = "",
                       include_unavailable: bool = False) -> str:
    """List doctors, optionally filtered by specialization.
    Staff roles (admin/nurse/doctor) can set include_unavailable=True to see ALL doctors
    including those marked unavailable. Useful when creating sessions or managing doctors.
    Args:
        specialization: e.g. 'Cardiology'. Empty = all doctors.
        include_unavailable: If True, includes unavailable doctors too. Default False (available only).
    """
    params = {}
    if specialization:
        params["specialization"] = specialization
    if include_unavailable:
        params["include_unavailable"] = "true"
    result = await _api("GET", "/doctors", ctx.context["token"], params=params)
    if isinstance(result, list):
        return _j([{
            "doctor_id": d.get("doctor_id") or d.get("id"),
            "name": d.get("full_name") or d.get("name"),
            "specialization": d.get("specialization"),
            "qualification": d.get("qualification"),
            "consultation_fee": d.get("consultation_fee"),
            "is_available": d.get("is_available"),
            "avg_rating": d.get("avg_rating"),
        } for d in result])
    return _j(result)


@function_tool
async def get_doctor_details(ctx: RunContextWrapper, doctor_id: str) -> str:
    """Get full details for a specific doctor.
    Args:
        doctor_id: UUID of the doctor.
    """
    return _j(await _api("GET", f"/doctors/{doctor_id}", ctx.context["token"]))


@function_tool
async def get_doctor_sessions(ctx: RunContextWrapper, doctor_id: str) -> str:
    """Get sessions for a doctor (today onward). For active sessions, includes the full patient list from queue.
    Accepts either doctor_id or user_id — the API resolves both.
    Args:
        doctor_id: UUID of the doctor (doctor_id or user_id both work).
    """
    from datetime import datetime as _dt
    token = ctx.context["token"]
    result = await _api("GET", f"/doctors/{doctor_id}/sessions", token,
                        params={"date_from": date.today().isoformat(), "include_all": "true"})
    if not isinstance(result, list):
        return _j(result)

    now = _dt.now()
    now_min = now.hour * 60 + now.minute
    today_str = date.today().isoformat()
    sessions = []

    for s in result:
        sid = s.get("session_id") or s.get("id")
        sess_date = str(s.get("session_date", ""))
        start_str = s.get("start_time", "")
        end_str = s.get("end_time", "")
        total = s.get("total_slots", 0)
        booked = s.get("booked_count", 0)
        max_per = s.get("max_patients_per_slot", 2)
        dur = s.get("slot_duration_minutes", 15)
        is_today = sess_date == today_str

        available = max(total * max_per - booked, 0)
        time_passed = False
        next_available_time = start_str

        if is_today:
            # Session fully ended?
            try:
                if end_str and now_min > _parse_hhmm(end_str):
                    time_passed = True
            except Exception:
                pass

            # For still-active today sessions: find next bookable slot,
            # cap available to future capacity only
            if not time_passed and start_str:
                try:
                    start_min = _parse_hhmm(start_str)
                    # Count past slots in one pass
                    past = 0
                    t = start_min
                    while t <= now_min and past < total:
                        past += 1
                        t += dur
                    next_available_time = _fmt_hhmm(t)
                    remaining = max(total - past, 0) * max_per
                    available = min(available, remaining)
                except Exception:
                    pass

        info = {
            "session_id": sid,
            "date": sess_date, "start": start_str, "end": end_str,
            "status": s.get("status"),
            "total_slots": total,
            "available_slots": available,
            "time_passed": time_passed,
            "next_available_time": next_available_time,
        }

        # For active sessions, include the queue
        if s.get("status") == "active" and sid:
            try:
                q = await _api("GET", f"/queue/{sid}", token)
                active = [e for e in q.get("queue", [])
                          if e.get("status") not in ("cancelled", "no_show")]
                info["patients"] = [{
                    "name": e.get("patient_name"), "status": e.get("status"),
                    "priority": e.get("priority_tier"), "is_emergency": e.get("is_emergency"),
                    "slot": e.get("slot_number"), "appointment_id": e.get("appointment_id"),
                } for e in active]
                info["patient_count"] = len(active)
            except Exception:
                info["patients"] = []
                info["patient_count"] = 0

        sessions.append(info)
    return _j(sessions)


@function_tool
async def get_operations_board(ctx: RunContextWrapper, board_date: str = "", department: str = "") -> str:
    """Get operations board showing all sessions grouped by department/doctor.
    Args:
        board_date: Date string YYYY-MM-DD (default today).
        department: Filter by department (optional).
    """
    params = {}
    if board_date:
        params["date"] = board_date
    if department:
        params["department"] = department
    return _j(await _api("GET", "/appointments/board", ctx.context["token"], params=params))


# ═══════════════════════════════════════════════════════════════
#  TOOLS — Patient (self-service)
# ═══════════════════════════════════════════════════════════════

@function_tool
async def book_appointment(ctx: RunContextWrapper, session_id: str, preferred_time: str = "", slot_number: int = 0, beneficiary_patient_id: str = "") -> str:
    """Book an appointment for self or a family member.
    Args:
        session_id: UUID of the session.
        preferred_time: Desired time in HH:MM 24-hour format (e.g. "11:30", "09:00", "14:15"). ALWAYS use this instead of slot_number when the user mentions a time.
        slot_number: Slot number (1-based). Only use this if the user explicitly says a slot number. Otherwise use preferred_time.
        beneficiary_patient_id: Patient UUID to book for. Empty = book for self.
    """
    pid = beneficiary_patient_id or ctx.context.get("patient_id", "")
    if not pid:
        return _j({"error": "No patient ID. Provide beneficiary_patient_id."})

    # If preferred_time is given, compute the correct slot_number from session details
    if preferred_time and slot_number <= 0:
        try:
            res = await _resolve_preferred_time_to_slot(preferred_time, session_id, ctx.context["token"])
            if "error" in res:
                return _j(res)
            slot_number = res["slot_number"]
        except Exception as e:
            logger.error(f"book_appointment time conversion failed: {e}", exc_info=True)
            return _j({"error": f"Could not convert time '{preferred_time}' to slot: {e}"})

    if slot_number <= 0:
        return _j({"error": "Provide either preferred_time (e.g. '11:30') or slot_number (1-based)."})

    return _j(await _api("POST", "/appointments/book", ctx.context["token"],
                         payload={"session_id": session_id, "slot_number": slot_number, "beneficiary_patient_id": pid}))


@function_tool
async def cancel_appointment(ctx: RunContextWrapper, appointment_id: str, reason: str = "Cancelled via chatbot") -> str:
    """Cancel an appointment. Warning: affects risk score.
    Args:
        appointment_id: UUID of appointment.
        reason: Cancellation reason.
    """
    return _j(await _api("POST", "/appointments/cancel", ctx.context["token"],
                         payload={"appointment_id": appointment_id, "reason": reason}))


@function_tool
async def undo_cancel_appointment(ctx: RunContextWrapper, appointment_id: str) -> str:
    """Undo a cancelled appointment (rebook it). Reverses risk penalty.
    Args:
        appointment_id: UUID of the cancelled appointment.
    """
    return _j(await _api("POST", "/appointments/undo-cancel", ctx.context["token"],
                         payload={"appointment_id": appointment_id, "reason": "Undo via chatbot"}))


@function_tool
async def get_my_appointments(ctx: RunContextWrapper) -> str:
    """Get the current patient's appointments (all statuses).
    Returns appointments where you are the patient OR the booker.
    Check 'booked_for' field: 'self' means your own appointment,
    otherwise it shows the beneficiary's name (family member).
    IMPORTANT: 'appointment_time' is the ACTUAL scheduled time (e.g. "16:30").
    ALWAYS show appointment_time to the user — NOT session_start."""
    my_pid = ctx.context.get("patient_id", "")
    result = await _api("GET", "/appointments/my", ctx.context["token"])
    if isinstance(result, list):
        result = {"appointments": result, "total": len(result)}
    if isinstance(result, dict) and "appointments" in result:
        appointments = []
        for a in result["appointments"]:
            # Determine if this is for self or a family member
            appt_patient_id = a.get("patient_id", "")
            patient_name = a.get("patient_name", "")
            if appt_patient_id == my_pid:
                booked_for = "self"
            else:
                booked_for = patient_name or "family member"

            # appointment_time is the ACTUAL time the patient should arrive
            raw_appt_time = a.get("slot_time")
            if raw_appt_time and raw_appt_time != "Emergency":
                # Convert to 12-hour format for clarity: "16:30" → "04:30 PM"
                try:
                    hh, mm = int(raw_appt_time[:2]), int(raw_appt_time[3:5])
                    period = "AM" if hh < 12 else "PM"
                    display_hh = hh if hh <= 12 else hh - 12
                    if display_hh == 0:
                        display_hh = 12
                    appt_time = f"{display_hh}:{mm:02d} {period} ({raw_appt_time})"
                except Exception:
                    appt_time = raw_appt_time
            else:
                appt_time = raw_appt_time  # "Emergency" or None

            appointments.append({
                "id": a.get("appointment_id"),
                "doctor": a.get("doctor_name"),
                "specialization": a.get("specialization"),
                "date": a.get("session_date"),
                "appointment_time": appt_time,
                "slot": a.get("slot_number"),
                "delay_minutes": a.get("delay_minutes", 0),
                "status": a.get("status"),
                "priority_tier": a.get("priority_tier"),
                "is_emergency": a.get("is_emergency"),
                "checked_in_at": str(a.get("checked_in_at", "")) if a.get("checked_in_at") else None,
                "patient_name": patient_name,
                "booked_for": booked_for,
            })
        return _j({"appointments": appointments, "total": result.get("total")})
    return _j(result)


@function_tool
async def get_my_profile(ctx: RunContextWrapper) -> str:
    """Get the current patient's profile."""
    return _j(await _api("GET", "/patients/me", ctx.context["token"]))


@function_tool
async def get_my_relationships(ctx: RunContextWrapper) -> str:
    """Get family members the patient can book for."""
    return _j(await _api("GET", "/patients/me/relationships", ctx.context["token"]))


@function_tool
async def update_family_member(
    ctx: RunContextWrapper,
    relationship_id: str,
    full_name: str = "",
    phone: str = "",
    gender: str = "",
    date_of_birth: str = "",
    blood_group: str = "",
    address: str = "",
    relationship_type: str = "",
    emergency_contact_name: str = "",
    emergency_contact_phone: str = "",
) -> str:
    """Update a family member's details. Only include fields that need changing.
    Args:
        relationship_id: The relationship_id from get_my_relationships.
        full_name: New full name (leave empty to keep current).
        phone: New phone number (leave empty to keep current).
        gender: New gender - male/female/other (leave empty to keep current).
        date_of_birth: New DOB as YYYY-MM-DD (leave empty to keep current).
        blood_group: New blood group like A+, O- etc (leave empty to keep current).
        address: New address (leave empty to keep current).
        relationship_type: New relationship - spouse/parent/child/sibling/guardian/other (leave empty to keep current).
        emergency_contact_name: Emergency contact name (leave empty to keep current).
        emergency_contact_phone: Emergency contact phone (leave empty to keep current).
    """
    payload = {}
    if full_name:
        payload["full_name"] = full_name
    if phone:
        payload["phone"] = phone
    if gender:
        payload["gender"] = gender
    if date_of_birth:
        payload["date_of_birth"] = date_of_birth
    if blood_group:
        payload["blood_group"] = blood_group
    if address:
        payload["address"] = address
    if relationship_type:
        payload["relationship_type"] = relationship_type
    if emergency_contact_name:
        payload["emergency_contact_name"] = emergency_contact_name
    if emergency_contact_phone:
        payload["emergency_contact_phone"] = emergency_contact_phone

    if not payload:
        return _j({"error": "No fields provided to update"})

    return _j(await _api(
        "PUT",
        f"/patients/me/relationships/{relationship_id}/beneficiary",
        ctx.context["token"],
        payload=payload,
    ))


# ═══════════════════════════════════════════════════════════════
#  TOOLS — Queue Management (Doctor/Nurse/Admin)
# ═══════════════════════════════════════════════════════════════

@function_tool
async def get_queue(ctx: RunContextWrapper, session_id: str) -> str:
    """Get the patient queue for a session.
    Args:
        session_id: UUID of the session.
    """
    return _j(await _api("GET", f"/queue/{session_id}", ctx.context["token"]))


@function_tool
async def get_emergency_patients(ctx: RunContextWrapper, session_id: str) -> str:
    """Get emergency patients waiting in a session's queue.
    Use this when asked about emergencies, emergency patients, or emergency queue.
    Returns only emergency entries (is_emergency=true, slot_number=0).
    Args:
        session_id: UUID of the session.
    """
    result = await _api("GET", f"/queue/{session_id}", ctx.context["token"])
    queue = result.get("queue", [])
    emergencies = [
        {
            "appointment_id": e.get("appointment_id"),
            "patient_id": e.get("patient_id"),
            "patient_name": e.get("patient_name"),
            "status": e.get("status"),
            "priority_tier": e.get("priority_tier"),
            "visual_priority": e.get("visual_priority"),
            "is_emergency": e.get("is_emergency"),
            "checked_in_at": str(e.get("checked_in_at", "")) if e.get("checked_in_at") else None,
        }
        for e in queue if e.get("is_emergency")
    ]
    return _j({
        "session_id": session_id,
        "doctor_name": result.get("doctor_name", ""),
        "emergency_count": len(emergencies),
        "emergency_patients": emergencies,
    })


@function_tool
async def checkin_patient(ctx: RunContextWrapper, appointment_id: str,
                          priority_tier: str = "NORMAL", is_emergency: bool = False,
                          visual_priority: int = 5) -> str:
    """Check in a patient who has arrived at the clinic.
    Args:
        appointment_id: UUID of the appointment.
        priority_tier: NORMAL, HIGH, or CRITICAL.
        is_emergency: True to mark as emergency during check-in.
        visual_priority: 1-10 urgency score (10 = most urgent).
    """
    payload = {"appointment_id": appointment_id, "priority_tier": priority_tier,
               "is_emergency": is_emergency, "visual_priority": visual_priority}
    return _j(await _api("POST", "/queue/checkin", ctx.context["token"], payload=payload))


@function_tool
async def call_patient(ctx: RunContextWrapper, session_id: str, appointment_id: str) -> str:
    """Call a specific checked-in patient to the doctor.
    Args:
        session_id: UUID of the session.
        appointment_id: UUID of the appointment.
    """
    return _j(await _api("POST", "/queue/call-patient", ctx.context["token"],
                         payload={"session_id": session_id, "appointment_id": appointment_id}))


@function_tool
async def call_next_patient(ctx: RunContextWrapper, session_id: str) -> str:
    """Call the next patient in the queue.
    Args:
        session_id: UUID of the session.
    """
    return _j(await _api("POST", "/queue/next", ctx.context["token"],
                         payload={"session_id": session_id}))


@function_tool
async def complete_appointment(ctx: RunContextWrapper, appointment_id: str, notes: str = "") -> str:
    """Mark a patient's appointment as completed (done with consultation).
    Args:
        appointment_id: UUID of the appointment.
        notes: Optional consultation notes.
    """
    payload = {"appointment_id": appointment_id}
    if notes:
        payload["notes"] = notes
    return _j(await _api("POST", "/queue/complete", ctx.context["token"], payload=payload))


@function_tool
async def escalate_priority(ctx: RunContextWrapper, appointment_id: str,
                            priority_tier: str = "", is_emergency: bool = False,
                            reason: str = "Priority updated by staff") -> str:
    """Change a patient's priority tier, emergency flag, or escalate in queue.
    Args:
        appointment_id: UUID of the appointment.
        priority_tier: NORMAL, HIGH, or CRITICAL. Empty to leave unchanged.
        is_emergency: True to mark as emergency, False to remove emergency flag.
        reason: Reason for the change (required, min 3 chars). Defaults to 'Priority updated by staff'.
    """
    payload = {"appointment_id": appointment_id, "reason": reason or "Priority updated by staff",
               "is_emergency": is_emergency}
    if priority_tier:
        payload["priority_tier"] = priority_tier
    return _j(await _api("POST", "/queue/escalate", ctx.context["token"], payload=payload))


@function_tool
async def set_patient_priority(ctx: RunContextWrapper, patient_name: str,
                                doctor_name: str = "", priority_tier: str = "NORMAL",
                                is_emergency: bool = False,
                                reason: str = "Priority updated by staff") -> str:
    """Set a patient's priority by name. Automatically finds the doctor, session, and appointment.
    Use this instead of escalate_priority when you have patient/doctor NAMES (not UUIDs).
    This tool handles the full lookup chain: doctor → session → queue → escalate.
    Args:
        patient_name: Name of the patient (partial match OK).
        doctor_name: Name of the doctor (partial match OK). If empty, searches all active sessions.
        priority_tier: NORMAL, HIGH, or CRITICAL.
        is_emergency: True to mark as emergency, False to remove emergency flag.
        reason: Reason for the change (min 3 chars).
    """
    token = ctx.context["token"]
    # Step 1: Find doctor
    doctors = await _api("GET", "/doctors", token)
    if not isinstance(doctors, list) or not doctors:
        return _j({"error": "No doctors found"})

    target_docs = doctors
    if doctor_name:
        target_docs = [d for d in doctors if doctor_name.lower() in (d.get("full_name") or "").lower()]
    if not target_docs:
        return _j({"error": f"Doctor '{doctor_name}' not found", "available": [d.get("full_name") for d in doctors]})

    # Step 2: Find active session with this patient
    patient_lower = patient_name.lower()
    for doc in target_docs:
        doc_id = doc.get("doctor_id") or doc.get("id")
        sessions = await _api("GET", f"/doctors/{doc_id}/sessions", token,
                               params={"date_from": date.today().isoformat()})
        if not isinstance(sessions, list):
            continue
        for sess in sessions:
            sid = sess.get("session_id") or sess.get("id")
            if not sid or sess.get("status") != "active":
                continue
            # Step 3: Get queue and find the patient
            queue_data = await _api("GET", f"/queue/{sid}", token)
            for entry in queue_data.get("queue", []):
                ename = (entry.get("patient_name") or "").lower()
                if patient_lower in ename:
                    appt_id = entry.get("appointment_id")
                    # Step 4: Escalate
                    payload = {
                        "appointment_id": appt_id,
                        "priority_tier": priority_tier,
                        "is_emergency": is_emergency,
                        "reason": reason or "Priority updated by staff",
                    }
                    result = await _api("POST", "/queue/escalate", token, payload=payload)
                    result["patient_name"] = entry.get("patient_name")
                    result["doctor_name"] = doc.get("full_name")
                    return _j(result)

    return _j({"error": f"Patient '{patient_name}' not found in any active queue" +
               (f" for doctor '{doctor_name}'" if doctor_name else "")})


@function_tool
async def mark_no_show(ctx: RunContextWrapper, appointment_id: str) -> str:
    """Mark a single patient as no-show.
    Args:
        appointment_id: UUID of the appointment.
    """
    return _j(await _api("POST", "/queue/no-show-single", ctx.context["token"],
                         payload={"appointment_id": appointment_id}))


@function_tool
async def set_appointment_duration(ctx: RunContextWrapper, appointment_id: str, duration_minutes: int) -> str:
    """Set custom duration for an appointment.
    Args:
        appointment_id: UUID of the appointment.
        duration_minutes: Custom duration in minutes.
    """
    return _j(await _api("POST", "/queue/set-duration", ctx.context["token"],
                         payload={"appointment_id": appointment_id, "duration_minutes": duration_minutes}))


@function_tool
async def undo_checkin(ctx: RunContextWrapper, appointment_id: str) -> str:
    """Undo a patient check-in (checked_in → booked).
    Args:
        appointment_id: UUID of the appointment.
    """
    return _j(await _api("POST", "/queue/undo-checkin", ctx.context["token"],
                         payload={"appointment_id": appointment_id}))


@function_tool
async def undo_send_to_doctor(ctx: RunContextWrapper, appointment_id: str) -> str:
    """Undo sending a patient to doctor (in_progress → checked_in).
    Args:
        appointment_id: UUID of the appointment.
    """
    return _j(await _api("POST", "/queue/undo-send", ctx.context["token"],
                         payload={"appointment_id": appointment_id}))


@function_tool
async def undo_complete_appointment(ctx: RunContextWrapper, appointment_id: str) -> str:
    """Undo appointment completion (completed → in_progress).
    Args:
        appointment_id: UUID of the appointment.
    """
    return _j(await _api("POST", "/queue/undo-complete", ctx.context["token"],
                         payload={"appointment_id": appointment_id}))


@function_tool
async def undo_no_show(ctx: RunContextWrapper, appointment_id: str) -> str:
    """Undo no-show mark (no_show → booked).
    Args:
        appointment_id: UUID of the appointment.
    """
    return _j(await _api("POST", "/queue/undo-noshow", ctx.context["token"],
                         payload={"appointment_id": appointment_id}))


# ═══════════════════════════════════════════════════════════════
#  TOOLS — Session Management (Doctor/Nurse/Admin)
# ═══════════════════════════════════════════════════════════════

@function_tool
async def create_session(ctx: RunContextWrapper, session_date: str, start_time: str, end_time: str,
                         doctor_id: str = "", slot_duration_minutes: int = 15,
                         max_patients_per_slot: int = 2) -> str:
    """Create and activate a session. If an inactive session already exists for that time, it auto-activates it.
    Doctors can omit doctor_id (defaults to self).
    Use this when the doctor says "activate afternoon session" or "create a new session".
    Standard times: Morning 09:00-13:00, Afternoon 14:00-17:00.
    Args:
        session_date: Date YYYY-MM-DD.
        start_time: Start time HH:MM (24h format, e.g. '14:00').
        end_time: End time HH:MM (24h format, e.g. '17:00').
        doctor_id: Doctor UUID. Empty = self (for doctors).
        slot_duration_minutes: Minutes per slot (default 15).
        max_patients_per_slot: Max patients per slot (default 2).
    """
    payload = {
        "session_date": session_date,
        "start_time": start_time,
        "end_time": end_time,
        "slot_duration_minutes": slot_duration_minutes,
        "max_patients_per_slot": max_patients_per_slot,
    }
    if doctor_id:
        payload["doctor_id"] = doctor_id
    return _j(await _api("POST", "/sessions/create", ctx.context["token"], payload=payload))


@function_tool
async def activate_session(ctx: RunContextWrapper, session_id: str) -> str:
    """Activate an inactive session (inactive → active).
    Args:
        session_id: UUID of the session.
    """
    return _j(await _api("POST", "/sessions/activate", ctx.context["token"],
                         payload={"session_id": session_id}))


@function_tool
async def deactivate_session(ctx: RunContextWrapper, session_id: str) -> str:
    """Deactivate an active session (active → inactive). Blocks if patient in progress.
    Args:
        session_id: UUID of the session.
    """
    return _j(await _api("POST", "/sessions/deactivate", ctx.context["token"],
                         payload={"session_id": session_id}))


@function_tool
async def doctor_checkin(ctx: RunContextWrapper, session_id: str) -> str:
    """Doctor checks in for their session (records arrival, calculates delay).
    Args:
        session_id: UUID of the session.
    """
    return _j(await _api("POST", "/sessions/checkin", ctx.context["token"],
                         payload={"session_id": session_id}))


@function_tool
async def update_delay(ctx: RunContextWrapper, session_id: str, delay_minutes: int) -> str:
    """Update the delay for a session.
    Args:
        session_id: UUID of the session.
        delay_minutes: New delay in minutes.
    """
    return _j(await _api("POST", "/sessions/update-delay", ctx.context["token"],
                         payload={"session_id": session_id, "delay_minutes": delay_minutes}))


@function_tool
async def set_overtime(ctx: RunContextWrapper, session_id: str, overtime_minutes: int) -> str:
    """Set overtime window for overbooked sessions.
    Args:
        session_id: UUID of the session.
        overtime_minutes: Extra minutes.
    """
    return _j(await _api("POST", "/sessions/overtime-window", ctx.context["token"],
                         payload={"session_id": session_id, "overtime_minutes": overtime_minutes}))


@function_tool
async def extend_session(ctx: RunContextWrapper, session_id: str, new_end_time: str, note: str = "") -> str:
    """Extend a session beyond its scheduled end time.
    Args:
        session_id: UUID of the session.
        new_end_time: New end time in HH:MM format (e.g. "20:00" for 8 PM).
        note: Optional reason for overtime.
    """
    return _j(await _api("POST", "/sessions/extend", ctx.context["token"],
                         payload={"session_id": session_id, "new_end_time": new_end_time, "note": note}))


@function_tool
async def complete_session(ctx: RunContextWrapper, session_id: str) -> str:
    """Complete/end a session. Remaining booked patients → no_show, checked_in → cancelled.
    Args:
        session_id: UUID of the session.
    """
    return _j(await _api("POST", "/sessions/complete-session", ctx.context["token"],
                         payload={"session_id": session_id}))


@function_tool
async def cancel_session(ctx: RunContextWrapper, session_id: str, reason: str) -> str:
    """Cancel an entire session. All appointments cancelled/no-show.
    Args:
        session_id: UUID of the session.
        reason: Cancellation reason (min 5 chars).
    """
    return _j(await _api("POST", "/sessions/cancel-session", ctx.context["token"],
                         payload={"session_id": session_id, "reason": reason}))


# ═══════════════════════════════════════════════════════════════
#  TOOLS — Staff Booking (Nurse/Admin)
# ═══════════════════════════════════════════════════════════════

@function_tool
async def search_patients(ctx: RunContextWrapper, query: str) -> str:
    """Search patients by name or phone number.
    Args:
        query: Name or phone to search.
    """
    return _j(await _api("GET", "/patients/search", ctx.context["token"], params={"q": query}))


@function_tool
async def get_patient_full_details(ctx: RunContextWrapper, patient_id: str) -> str:
    """Get full patient details including profile, appointments, and family/beneficiary relationships.
    Args:
        patient_id: UUID of the patient.
    """
    return _j(await _api("GET", f"/admin/patients/{patient_id}", ctx.context["token"]))


@function_tool
async def update_patient_details(ctx: RunContextWrapper, patient_id: str,
                                  full_name: str = "", email: str = "", phone: str = "",
                                  blood_group: str = "", gender: str = "", address: str = "",
                                  abha_id: str = "", emergency_contact_name: str = "",
                                  emergency_contact_phone: str = "") -> str:
    """Update a patient's profile details (staff only). Only include fields that need changing.
    Args:
        patient_id: UUID of the patient.
        full_name: New name (leave empty to keep current).
        email: New email (leave empty to keep current).
        phone: New phone (leave empty to keep current).
        blood_group: New blood group (leave empty to keep current).
        gender: New gender (leave empty to keep current).
        address: New address (leave empty to keep current).
        abha_id: New ABHA ID (leave empty to keep current).
        emergency_contact_name: New emergency contact name (leave empty to keep current).
        emergency_contact_phone: New emergency contact phone (leave empty to keep current).
    """
    payload = {}
    if full_name: payload["full_name"] = full_name
    if email: payload["email"] = email
    if phone: payload["phone"] = phone
    if blood_group: payload["blood_group"] = blood_group
    if gender: payload["gender"] = gender
    if address: payload["address"] = address
    if abha_id: payload["abha_id"] = abha_id
    if emergency_contact_name: payload["emergency_contact_name"] = emergency_contact_name
    if emergency_contact_phone: payload["emergency_contact_phone"] = emergency_contact_phone
    if not payload:
        return _j({"error": "No fields to update. Provide at least one field."})
    result = await _api("PUT", f"/admin/patients/{patient_id}/update", ctx.context["token"], payload=payload)
    # The API now returns current_data with the actual DB values after update.
    # IMPORTANT: Always report the values from current_data, NOT from memory or the input values.
    if "error" in result:
        return _j({"error": result["error"], "attempted_fields": list(payload.keys()),
                    "hint": "The update FAILED. Do NOT tell the user it succeeded."})
    return _j(result)


@function_tool
async def staff_book(ctx: RunContextWrapper, session_id: str, slot_number: int, patient_id: str) -> str:
    """Book appointment on behalf of a patient (staff only).
    Args:
        session_id: UUID of session.
        slot_number: Slot number (1-based).
        patient_id: UUID of the patient.
    """
    return _j(await _api("POST", "/appointments/staff-book", ctx.context["token"],
                         payload={"session_id": session_id, "slot_number": slot_number, "patient_id": patient_id}))


@function_tool
async def emergency_book(ctx: RunContextWrapper, session_id: str, patient_id: str, reason: str,
                          priority_tier: str = "CRITICAL") -> str:
    """Add an emergency patient to a session — NO slot needed. Patient goes directly into the queue.
    Args:
        session_id: UUID of session.
        patient_id: UUID of patient.
        reason: Emergency reason (min 5 chars).
        priority_tier: CRITICAL (default), HIGH, or NORMAL.
    """
    return _j(await _api("POST", "/appointments/emergency", ctx.context["token"],
                         payload={"session_id": session_id, "patient_id": patient_id,
                                  "reason": reason, "priority_tier": priority_tier}))


@function_tool
async def staff_register_and_book(
    ctx: RunContextWrapper, session_id: str, slot_number: int,
    full_name: str, phone: str = "", gender: str = "other",
    date_of_birth: str = "", symptoms: str = "",
) -> str:
    """Register a NEW walk-in patient and book an appointment in one step.
    Use this when the patient does NOT exist in the system yet.
    Args:
        session_id: UUID of the session to book in.
        slot_number: Slot number (1-based).
        full_name: Patient's full name (required, min 2 chars).
        phone: Phone number (optional).
        gender: male, female, or other.
        date_of_birth: YYYY-MM-DD format (optional).
        symptoms: Reason for visit (optional, added as notes).
    """
    payload = {
        "session_id": session_id,
        "slot_number": slot_number,
        "full_name": full_name,
    }
    if phone:
        payload["phone"] = phone
    if gender:
        payload["gender"] = gender
    if date_of_birth:
        payload["date_of_birth"] = date_of_birth
    if symptoms:
        payload["symptoms"] = symptoms
    return _j(await _api("POST", "/appointments/staff-register-book", ctx.context["token"], payload=payload))


@function_tool
async def emergency_register_and_book(
    ctx: RunContextWrapper, session_id: str,
    full_name: str, reason: str = "Emergency walk-in",
    phone: str = "", gender: str = "other",
    date_of_birth: str = "",
) -> str:
    """Register a NEW walk-in patient and book them as an EMERGENCY in one step.
    Use this when the patient does NOT exist in the system and needs emergency booking.
    The patient gets slot_number=0, is_emergency=True, CRITICAL priority, and is auto-checked-in.
    Args:
        session_id: UUID of the session.
        full_name: Patient's full name (required, min 2 chars).
        reason: Emergency reason (min 5 chars).
        phone: Phone number (optional).
        gender: male, female, or other.
        date_of_birth: YYYY-MM-DD format (optional).
    """
    payload = {
        "session_id": session_id,
        "full_name": full_name,
        "reason": reason,
    }
    if phone:
        payload["phone"] = phone
    if gender:
        payload["gender"] = gender
    if date_of_birth:
        payload["date_of_birth"] = date_of_birth
    return _j(await _api("POST", "/appointments/emergency-register-book", ctx.context["token"], payload=payload))


@function_tool
async def staff_cancel_appointment(ctx: RunContextWrapper, appointment_id: str, reason: str = "Cancelled by staff") -> str:
    """Cancel an appointment as staff (doctor/nurse/admin). Sends cancellation email and calendar event.
    Args:
        appointment_id: UUID of appointment.
        reason: Cancellation reason.
    """
    return _j(await _api("POST", "/appointments/staff-cancel", ctx.context["token"],
                         payload={"appointment_id": appointment_id, "reason": reason}))


@function_tool
async def get_my_doctor_sessions(ctx: RunContextWrapper, date_from: str = "", date_to: str = "") -> str:
    """Get the current doctor's own sessions. Only works for doctor role.
    Automatically resolves the doctor_id from the logged-in user.
    Args:
        date_from: Start date YYYY-MM-DD (default: today).
        date_to: End date YYYY-MM-DD (optional).
    """
    doctor_id = ctx.context.get("doctor_id", "")
    if not doctor_id:
        return _j({"error": "Not a doctor or doctor_id not available."})
    params = {"date_from": date_from or date.today().isoformat(), "include_all": "true"}
    if date_to:
        params["date_to"] = date_to
    result = await _api("GET", f"/doctors/{doctor_id}/sessions", ctx.context["token"], params=params)
    if isinstance(result, list):
        return _j([{
            "session_id": s.get("session_id") or s.get("id"),
            "date": s.get("session_date"), "start": s.get("start_time"), "end": s.get("end_time"),
            "status": s.get("status"),
            "slot_duration": s.get("slot_duration_minutes"),
            "available": s.get("total_slots", 0) - s.get("booked_count", 0),
            "total_slots": s.get("total_slots"), "booked": s.get("booked_count"),
            "max_per_slot": s.get("max_patients_per_slot"),
        } for s in result])
    return _j(result)


@function_tool
async def reassign_appointment(ctx: RunContextWrapper, appointment_id: str, target_session_id: str, preferred_time: str = "", target_slot_number: int = 0) -> str:
    """Reassign an appointment to a different time slot or doctor's session.
    Use this to change an appointment's time (same doctor, different slot) OR move to another doctor.
    Args:
        appointment_id: UUID of the appointment to reassign.
        target_session_id: UUID of the destination session (can be the SAME session for time change, or a different doctor's session).
        preferred_time: Desired time in HH:MM 24-hour format (e.g. "16:00" for 4 PM). ALWAYS use this when the user mentions a time. The system auto-computes the correct slot.
        target_slot_number: Slot number (1-based). Only use this if user explicitly says a slot number. Otherwise use preferred_time.
    """
    # If preferred_time given, auto-compute slot from session details
    if preferred_time and target_slot_number <= 0:
        try:
            res = await _resolve_preferred_time_to_slot(preferred_time, target_session_id, ctx.context["token"])
            if "error" in res:
                return _j(res)
            target_slot_number = res["slot_number"]
        except Exception as e:
            logger.error(f"reassign_appointment time conversion failed: {e}", exc_info=True)
            return _j({"error": f"Could not convert time '{preferred_time}' to slot: {e}"})

    if target_slot_number <= 0:
        return _j({"error": "Provide either preferred_time (e.g. '16:00') or target_slot_number (1-based)."})

    return _j(await _api("POST", "/appointments/reassign", ctx.context["token"],
                         payload={"appointment_id": appointment_id,
                                  "target_session_id": target_session_id,
                                  "target_slot_number": target_slot_number}))


# ═══════════════════════════════════════════════════════════════
#  TOOLS — Admin Management
# ═══════════════════════════════════════════════════════════════

@function_tool
async def admin_get_stats(ctx: RunContextWrapper) -> str:
    """Get today's dashboard statistics (total appointments, patients, etc.)."""
    return _j(await _api("GET", "/admin/stats", ctx.context["token"]))


@function_tool
async def admin_list_users(ctx: RunContextWrapper, role: str = "", include_inactive: bool = False) -> str:
    """List all system users, optionally filtered by role.
    Args:
        role: Filter by role (patient, doctor, nurse, admin). Empty = all.
        include_inactive: Include deactivated users.
    """
    params = {}
    if role:
        params["role"] = role
    if include_inactive:
        params["include_inactive"] = "true"
    return _j(await _api("GET", "/admin/users", ctx.context["token"], params=params))


@function_tool
async def admin_create_user(ctx: RunContextWrapper, email: str, password: str, full_name: str, role: str,
                             specialization: str = "", qualification: str = "", consultation_fee: float = 0) -> str:
    """Create a new staff user (doctor, nurse, or admin).
    Args:
        email: User email.
        password: Password.
        full_name: Full name.
        role: doctor, nurse, or admin.
        specialization: Required for doctors.
        qualification: Required for doctors.
        consultation_fee: For doctors, default 0.
    """
    payload = {"email": email, "password": password, "full_name": full_name, "role": role}
    if specialization:
        payload["specialization"] = specialization
    if qualification:
        payload["qualification"] = qualification
    if consultation_fee:
        payload["consultation_fee"] = consultation_fee
    return _j(await _api("POST", "/admin/users", ctx.context["token"], payload=payload))


@function_tool
async def admin_toggle_user(ctx: RunContextWrapper, user_id: str) -> str:
    """Activate or deactivate a user account.
    Args:
        user_id: UUID of the user.
    """
    return _j(await _api("PUT", f"/admin/users/{user_id}/toggle", ctx.context["token"]))


@function_tool
async def admin_list_patients(ctx: RunContextWrapper, search: str = "", high_risk_only: bool = False) -> str:
    """List patients with optional search and risk filter.
    Args:
        search: Search by name/phone.
        high_risk_only: Only show high-risk patients.
    """
    params = {"limit": 50, "offset": 0}
    if search:
        params["search"] = search
    if high_risk_only:
        params["high_risk_only"] = "true"
    return _j(await _api("GET", "/admin/patients", ctx.context["token"], params=params))


@function_tool
async def admin_reset_risk(ctx: RunContextWrapper, patient_id: str, new_score: float = 0.0) -> str:
    """Reset a patient's risk score.
    Args:
        patient_id: UUID of the patient.
        new_score: New score value (default 0).
    """
    return _j(await _api("PUT", f"/admin/patients/{patient_id}/reset-risk", ctx.context["token"],
                         payload={"patient_id": patient_id, "new_score": new_score}))


@function_tool
async def admin_get_audit(ctx: RunContextWrapper, action: str = "", from_date: str = "", to_date: str = "") -> str:
    """Query audit logs.
    Args:
        action: Filter by action type (e.g. BOOKED, CANCELLED).
        from_date: Start date YYYY-MM-DD.
        to_date: End date YYYY-MM-DD.
    """
    params = {"limit": 30, "offset": 0}
    if action:
        params["action"] = action
    if from_date:
        params["from_date"] = from_date
    if to_date:
        params["to_date"] = to_date
    return _j(await _api("GET", "/admin/audit", ctx.context["token"], params=params))


@function_tool
async def admin_list_sessions(ctx: RunContextWrapper, session_date: str = "", status: str = "",
                               specialization: str = "") -> str:
    """List all sessions with filters.
    Args:
        session_date: Date YYYY-MM-DD.
        status: active, inactive, completed, cancelled.
        specialization: Department filter.
    """
    params = {}
    if session_date:
        params["date_str"] = session_date
    if status:
        params["status"] = status
    if specialization:
        params["specialization"] = specialization
    return _j(await _api("GET", "/admin/sessions", ctx.context["token"], params=params))


@function_tool
async def admin_get_config(ctx: RunContextWrapper) -> str:
    """Get all scheduling configuration (slot duration, clinic hours, etc.)."""
    return _j(await _api("GET", "/admin/config", ctx.context["token"]))


@function_tool
async def admin_update_config(ctx: RunContextWrapper, key: str, value: str) -> str:
    """Update a scheduling config value.
    Args:
        key: Config key (e.g. slot_duration_minutes, clinic_close).
        value: New value.
    """
    return _j(await _api("PUT", f"/admin/config/{key}", ctx.context["token"], payload={"value": value}))


@function_tool
async def admin_list_doctors(ctx: RunContextWrapper, specialization: str = "") -> str:
    """List all doctors with full details including availability, fees, qualification.
    Args:
        specialization: Filter by department. Empty = all doctors.
    """
    params = {}
    if specialization:
        params["specialization"] = specialization
    return _j(await _api("GET", "/admin/doctors", ctx.context["token"], params=params))


@function_tool
async def admin_update_doctor(ctx: RunContextWrapper, doctor_id: str,
                               specialization: str = "", qualification: str = "",
                               license_number: str = "", consultation_fee: float = 0,
                               max_patients_per_slot: int = 0,
                               is_available: bool | None = None) -> str:
    """Update a doctor's settings (specialization, fee, availability, etc.).
    Args:
        doctor_id: UUID of the doctor.
        specialization: New specialization. Empty = no change.
        qualification: New qualification. Empty = no change.
        license_number: New license. Empty = no change.
        consultation_fee: New fee. 0 = no change.
        max_patients_per_slot: New max. 0 = no change.
        is_available: Set availability. None = no change.
    """
    payload = {}
    if specialization:
        payload["specialization"] = specialization
    if qualification:
        payload["qualification"] = qualification
    if license_number:
        payload["license_number"] = license_number
    if consultation_fee:
        payload["consultation_fee"] = consultation_fee
    if max_patients_per_slot:
        payload["max_patients_per_slot"] = max_patients_per_slot
    if is_available is not None:
        payload["is_available"] = is_available
    if not payload:
        return _j({"error": "No fields to update"})
    return _j(await _api("PUT", f"/admin/doctors/{doctor_id}", ctx.context["token"], payload=payload))


@function_tool
async def admin_update_user(ctx: RunContextWrapper, user_id: str,
                             full_name: str = "", email: str = "", phone: str = "") -> str:
    """Update a user's personal details (name, email, phone).
    Args:
        user_id: UUID of the user.
        full_name: New name. Empty = no change.
        email: New email. Empty = no change.
        phone: New phone. Empty = no change.
    """
    payload = {}
    if full_name:
        payload["full_name"] = full_name
    if email:
        payload["email"] = email
    if phone:
        payload["phone"] = phone
    if not payload:
        return _j({"error": "No fields to update"})
    return _j(await _api("PUT", f"/admin/users/{user_id}", ctx.context["token"], payload=payload))


@function_tool
async def admin_update_patient(ctx: RunContextWrapper, patient_id: str,
                                full_name: str = "", phone: str = "", email: str = "",
                                gender: str = "", blood_group: str = "",
                                address: str = "", abha_id: str = "",
                                emergency_contact_name: str = "",
                                emergency_contact_phone: str = "") -> str:
    """Update a patient's profile (name, phone, blood group, emergency contact, etc.).
    Args:
        patient_id: UUID of the patient.
        full_name: New name. Empty = no change.
        phone: New phone. Empty = no change.
        email: New email. Empty = no change.
        gender: Male, Female, or Other. Empty = no change.
        blood_group: A+, A-, B+, B-, O+, O-, AB+, AB-. Empty = no change.
        address: New address. Empty = no change.
        abha_id: ABHA/UHID. Empty = no change.
        emergency_contact_name: Emergency contact name. Empty = no change.
        emergency_contact_phone: Emergency contact phone. Empty = no change.
    """
    payload = {}
    for key, val in [("full_name", full_name), ("phone", phone), ("email", email),
                     ("gender", gender), ("blood_group", blood_group), ("address", address),
                     ("abha_id", abha_id), ("emergency_contact_name", emergency_contact_name),
                     ("emergency_contact_phone", emergency_contact_phone)]:
        if val:
            payload[key] = val
    if not payload:
        return _j({"error": "No fields to update"})
    return _j(await _api("PUT", f"/admin/patients/{patient_id}/update", ctx.context["token"], payload=payload))


@function_tool
async def admin_add_beneficiary(ctx: RunContextWrapper, patient_id: str,
                                 beneficiary_name: str, relationship_type: str,
                                 phone: str = "", gender: str = "other",
                                 blood_group: str = "",
                                 custom_relationship: str = "") -> str:
    """Add a family member (beneficiary) to a patient.
    Args:
        patient_id: UUID of the patient (booker).
        beneficiary_name: Full name of the family member.
        relationship_type: parent, child, spouse, sibling, guardian, or other.
        phone: Phone number. Optional.
        gender: male, female, or other. Default other.
        blood_group: Blood group. Optional.
        custom_relationship: If relationship_type is 'other', specify the actual relationship (e.g. cousin, uncle).
    """
    payload = {"beneficiary_name": beneficiary_name, "relationship_type": relationship_type,
               "gender": gender}
    if phone:
        payload["phone"] = phone
    if blood_group:
        payload["blood_group"] = blood_group
    if custom_relationship:
        payload["custom_relationship"] = custom_relationship
    return _j(await _api("POST", f"/admin/patients/{patient_id}/add-beneficiary",
                         ctx.context["token"], payload=payload))


@function_tool
async def admin_update_session(ctx: RunContextWrapper, session_id: str,
                                start_time: str = "", end_time: str = "",
                                slot_duration_minutes: int = 0,
                                max_patients_per_slot: int = 0,
                                notes: str = "") -> str:
    """Edit a session's time, slot duration, max patients, or notes. Recalculates total slots automatically.
    Args:
        session_id: UUID of the session.
        start_time: New start time HH:MM. Empty = no change.
        end_time: New end time HH:MM. Empty = no change.
        slot_duration_minutes: New duration per slot (5-60). 0 = no change.
        max_patients_per_slot: New max per slot (1-10). 0 = no change.
        notes: Session notes. Empty = no change.
    """
    payload = {}
    if start_time:
        payload["start_time"] = start_time
    if end_time:
        payload["end_time"] = end_time
    if slot_duration_minutes:
        payload["slot_duration_minutes"] = slot_duration_minutes
    if max_patients_per_slot:
        payload["max_patients_per_slot"] = max_patients_per_slot
    if notes:
        payload["notes"] = notes
    if not payload:
        return _j({"error": "No fields to update"})
    return _j(await _api("PUT", f"/admin/sessions/{session_id}/update",
                         ctx.context["token"], payload=payload))


@function_tool
async def admin_get_patient_detail(ctx: RunContextWrapper, patient_id: str) -> str:
    """Get full patient details including profile, relationships, and appointments.
    Args:
        patient_id: UUID of the patient.
    """
    return _j(await _api("GET", f"/admin/patients/{patient_id}", ctx.context["token"]))


# ─── Rating & Feedback Tools ──────────────────────────────────

@function_tool
async def submit_rating(ctx: RunContextWrapper, appointment_id: str, rating: int,
                        review: str = "") -> str:
    """Submit a rating for a completed appointment. Patients only.
    Args:
        appointment_id: The completed appointment UUID.
        rating: 1-5 star rating.
        review: Optional text feedback about the doctor visit.
    """
    payload = {"appointment_id": appointment_id, "rating": rating}
    if review:
        payload["review"] = review
    return _j(await _api("POST", "/ratings", ctx.context["token"], payload=payload))


@function_tool
async def get_doctor_ratings(ctx: RunContextWrapper, doctor_id: str) -> str:
    """Get recent ratings/reviews for a specific doctor.
    Args:
        doctor_id: The doctor UUID (from list_doctors).
    """
    return _j(await _api("GET", f"/ratings/doctor/{doctor_id}", ctx.context["token"]))


@function_tool
async def get_doctor_rating_stats(ctx: RunContextWrapper, doctor_id: str) -> str:
    """Get average rating and total count for a doctor.
    Args:
        doctor_id: The doctor UUID (from list_doctors).
    """
    return _j(await _api("GET", f"/ratings/doctor/{doctor_id}/stats", ctx.context["token"]))


@function_tool
async def search_feedback(ctx: RunContextWrapper, query: str, doctor_id: str = "") -> str:
    """Search patient feedback/reviews using natural language (RAG-powered).
    Use this to find reviews about specific topics like 'wait times', 'bedside manner', etc.
    Args:
        query: Natural language search query (e.g. 'complaints about wait times', 'positive bedside manner').
        doctor_id: Optional — filter to a specific doctor UUID.
    """
    from go.services.rag_service import search_reviews
    results = search_reviews(query=query, doctor_id=doctor_id, n_results=10)
    if not results:
        return _j({"message": "No matching reviews found.", "results": []})
    return _j({"total_found": len(results), "results": results})


# ═══════════════════════════════════════════════════════════════
#  TOOL GROUPS — organized by capability
# ═══════════════════════════════════════════════════════════════

_RATING_TOOLS = [submit_rating, get_doctor_ratings, get_doctor_rating_stats, search_feedback]

_INFO_TOOLS = [list_departments, list_doctors, get_doctor_details, get_doctor_sessions]
_STAFF_INFO_TOOLS = _INFO_TOOLS + [get_operations_board]

_PATIENT_TOOLS = [book_appointment, cancel_appointment, undo_cancel_appointment,
                  reassign_appointment,
                  get_my_appointments, get_my_profile, get_my_relationships,
                  update_family_member]

_QUEUE_TOOLS = [get_queue, get_emergency_patients, set_patient_priority,
                checkin_patient, call_patient, call_next_patient,
                complete_appointment, mark_no_show, escalate_priority,
                set_appointment_duration, undo_checkin, undo_send_to_doctor,
                undo_complete_appointment, undo_no_show]

_SESSION_TOOLS = [create_session, activate_session, deactivate_session, doctor_checkin,
                  update_delay, set_overtime, extend_session,
                  complete_session, cancel_session]

_STAFF_BOOK_TOOLS = [search_patients, get_patient_full_details, update_patient_details,
                     staff_book,
                     emergency_book,
                     staff_cancel_appointment, reassign_appointment]

_DOCTOR_EXTRA_TOOLS = [get_my_doctor_sessions] + _STAFF_BOOK_TOOLS

_NURSE_ADMIN_TOOLS = [admin_get_stats,
                      admin_list_doctors,
                      admin_list_patients, admin_get_patient_detail, admin_update_patient,
                      admin_add_beneficiary, admin_reset_risk,
                      admin_list_sessions, admin_update_session]

_ADMIN_TOOLS = [admin_get_stats, admin_list_users, admin_toggle_user,
                admin_update_user,
                admin_list_doctors, admin_update_doctor,
                admin_list_patients, admin_get_patient_detail, admin_update_patient,
                admin_add_beneficiary, admin_reset_risk,
                admin_list_sessions, admin_update_session,
                admin_get_audit, admin_get_config, admin_update_config]
