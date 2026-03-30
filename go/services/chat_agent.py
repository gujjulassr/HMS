"""
DPMS — AI Chatbot Agent Service (OpenAI Agents SDK)
=====================================================
One agent per role. No sub-agents, no handoffs.
Each role gets exactly the tools that match its dashboard capabilities.
"""

import json
import logging
import os
import pathlib
from datetime import date
from typing import Optional

import httpx
from agents import Agent, Runner, SQLiteSession, function_tool, RunContextWrapper
from agents.memory import OpenAIResponsesCompactionSession

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ─── Internal API client ─────────────────────────────────────
API_BASE = "http://localhost:8000/api"


def _clear_proxy_env():
    """Remove proxy env vars that break httpx (socks5h not supported)."""
    for v in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
              "HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy"):
        os.environ.pop(v, None)


async def _api(
    method: str, path: str, token: str,
    payload: dict | None = None, params: dict | None = None,
) -> dict:
    """Authenticated call to FastAPI backend."""
    _clear_proxy_env()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{API_BASE}{path}"
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            if method == "GET":
                r = await client.get(url, headers=headers, params=params)
            elif method == "POST":
                r = await client.post(url, headers=headers, json=payload)
            elif method == "PUT":
                r = await client.put(url, headers=headers, json=payload)
            else:
                return {"error": f"Unsupported method: {method}"}
            if r.status_code >= 400:
                try:
                    err = r.json()
                except Exception:
                    err = r.text
                return {"error": str(err), "status_code": r.status_code}
            return r.json()
    except httpx.ConnectError as e:
        logger.error(f"API connection error for {url}: {e}")
        return {"error": f"Cannot connect to backend at {url}. Is the server running?"}
    except httpx.TimeoutException:
        logger.error(f"API timeout for {url}")
        return {"error": f"Request timed out for {url}"}
    except Exception as e:
        logger.error(f"API call error for {url}: {e}", exc_info=True)
        return {"error": f"API call failed: {type(e).__name__}: {e}"}


def _j(obj) -> str:
    """JSON-serialize for agent output."""
    return json.dumps(obj, default=str)


# ═══════════════════════════════════════════════════════════════
#  TOOLS — Information & Discovery
# ═══════════════════════════════════════════════════════════════

@function_tool
async def list_departments(ctx: RunContextWrapper) -> str:
    """List all hospital departments/specializations."""
    result = await _api("GET", "/appointments/departments", ctx.context["token"])
    logger.info(f"list_departments result: {str(result)[:300]}")
    return _j(result)


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
    logger.info(f"list_doctors called: specialization='{specialization}', include_unavailable={include_unavailable}, token present={bool(ctx.context.get('token'))}")
    result = await _api("GET", "/doctors", ctx.context["token"], params=params)
    logger.info(f"list_doctors result type={type(result).__name__}, is_list={isinstance(result, list)}, "
                f"content_preview={str(result)[:200]}")
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
    token = ctx.context["token"]
    params = {"date_from": date.today().isoformat(), "include_all": "true"}
    logger.info(f"get_doctor_sessions called: doctor_id='{doctor_id}'")
    result = await _api("GET", f"/doctors/{doctor_id}/sessions", token, params=params)
    logger.info(f"get_doctor_sessions result: type={type(result).__name__}, preview={str(result)[:300]}")
    if isinstance(result, list):
        sessions = []
        for s in result:
            sid = s.get("session_id") or s.get("id")
            info = {
                "session_id": sid,
                "date": s.get("session_date"), "start": s.get("start_time"), "end": s.get("end_time"),
                "status": s.get("status"),
                "total_slots": s.get("total_slots"),
            }
            # For active/today sessions, include full patient list
            if s.get("status") == "active" and sid:
                try:
                    q = await _api("GET", f"/queue/{sid}", token)
                    queue = q.get("queue", [])
                    active = [e for e in queue if e.get("status") not in ("cancelled", "no_show")]
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
    return _j(result)


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
async def book_appointment(ctx: RunContextWrapper, session_id: str, slot_number: int, beneficiary_patient_id: str = "") -> str:
    """Book an appointment for self or a family member.
    Args:
        session_id: UUID of the session.
        slot_number: Slot number (1-based).
        beneficiary_patient_id: Patient UUID to book for. Empty = book for self.
    """
    pid = beneficiary_patient_id or ctx.context.get("patient_id", "")
    if not pid:
        return _j({"error": "No patient ID. Provide beneficiary_patient_id."})
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
    """Get the current patient's appointments (all statuses)."""
    result = await _api("GET", "/appointments/my", ctx.context["token"])
    if isinstance(result, list):
        result = {"appointments": result, "total": len(result)}
    if isinstance(result, dict) and "appointments" in result:
        return _j({"appointments": [{
            "id": a.get("appointment_id"), "doctor": a.get("doctor_name"),
            "specialization": a.get("specialization"), "date": a.get("session_date"),
            "time": a.get("start_time"), "slot": a.get("slot_number"), "status": a.get("status"),
        } for a in result["appointments"]], "total": result.get("total")})
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
async def reassign_appointment(ctx: RunContextWrapper, appointment_id: str, target_session_id: str, target_slot_number: int) -> str:
    """Reassign an appointment to a different time slot or doctor's session.
    Use this to change an appointment's time (same doctor, different slot) OR move to another doctor.
    Args:
        appointment_id: UUID of the appointment to reassign.
        target_session_id: UUID of the destination session (can be the SAME session for time change, or a different doctor's session).
        target_slot_number: Slot number in the target session (1-based). Calculate from session start_time and slot_duration.
            Example: session starts at 09:00 with 15-min slots → slot 1=09:00, slot 2=09:15, ..., slot 9=11:00.
    """
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


# ═══════════════════════════════════════════════════════════════
#  TOOL GROUPS — organized by capability
# ═══════════════════════════════════════════════════════════════

_INFO_TOOLS = [list_departments, list_doctors, get_doctor_details, get_doctor_sessions]
_STAFF_INFO_TOOLS = _INFO_TOOLS + [get_operations_board]

_PATIENT_TOOLS = [book_appointment, cancel_appointment, undo_cancel_appointment,
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
                     staff_book, staff_register_and_book,
                     emergency_book, staff_cancel_appointment, reassign_appointment]

_DOCTOR_EXTRA_TOOLS = [get_my_doctor_sessions, search_patients, get_patient_full_details,
                       update_patient_details, staff_book,
                       staff_register_and_book, emergency_book,
                       staff_cancel_appointment, reassign_appointment]

_ADMIN_TOOLS = [admin_get_stats, admin_list_users, admin_create_user, admin_toggle_user,
                admin_list_patients, admin_reset_risk, admin_get_audit,
                admin_list_sessions, admin_get_config, admin_update_config]


# ═══════════════════════════════════════════════════════════════
#  ROLE CONFIG — one agent per role, tools matching dashboard
# ═══════════════════════════════════════════════════════════════

MODEL = "gpt-4o"

ROLE_CONFIG = {
    "patient": {
        "tools": _INFO_TOOLS + _PATIENT_TOOLS,
        "instructions": """You are the Hospital AI Assistant for PATIENTS.

CRITICAL RULES:
1. ONLY do what the patient explicitly asks. NEVER call tools or take actions unprompted.
   - If patient says "hi" or "hello" → just greet back. Do NOT fetch appointments, doctors, or anything.
   - NEVER auto-fetch data to "be helpful". Wait for the patient to ask.
2. Be concise and friendly. Short natural responses, not walls of text.
3. **NEVER answer from conversation history for real-time data.** Appointment status, session availability, queue — these change constantly. ALWAYS call tools fresh.
4. Use tools to get REAL data — never guess doctors, sessions, or IDs.
4. Confirm before booking or cancelling.
5. Never provide medical diagnoses — only help with logistics.
6. If a tool call returns an error, try an alternative tool. NEVER give up after one failure.
   - For finding doctors: ALWAYS use list_doctors(specialization=...) first, NOT list_departments.

FINDING DOCTORS (most common patient request):
- Patient says a specialty ("cardiologist", "heart", "bone", "skin", etc.)
  → call list_doctors(specialization="Cardiology") — use the proper medical name
  → common mappings: heart=Cardiology, bone=Orthopedics, skin=Dermatology, brain/neuro=Neurology,
    child/kids=Pediatrics, eye=Ophthalmology, ENT/ear/nose/throat=ENT, teeth=Dental,
    women/pregnancy=Gynecology, general/fever/cold=General Medicine
- Patient says symptoms ("chest pain", "headache")
  → map to likely department, then call list_doctors(specialization=...)
  → don't diagnose, just find the right department
- Patient says "show all doctors" → call list_doctors() with no specialization
- If list_doctors returns empty, call list_departments to show what's available

BOOKING FLOW:
1. list_doctors(specialization=...) → show doctor names with fees
2. Patient picks a doctor → get_doctor_sessions(doctor_id) → show dates/times with available slots
3. Patient picks a session and slot → book_appointment
Always confirm doctor + date + slot before booking.

OTHER CAPABILITIES:
- View appointments: get_my_appointments
- Cancel/undo-cancel: cancel_appointment, undo_cancel_appointment
- Profile & family: get_my_profile, get_my_relationships, update_family_member
  Family data includes: name, phone, gender, age, blood_group, dob, abha_id, address, email, emergency contacts.
  Show ALL details when asked — don't say "not available" if the data exists in the response.""",
    },
    "doctor": {
        "tools": _STAFF_INFO_TOOLS + _QUEUE_TOOLS + _SESSION_TOOLS + _DOCTOR_EXTRA_TOOLS,
        "instructions": """You are the Hospital AI Assistant for DOCTORS.

CRITICAL RULES — follow these STRICTLY:
1. ONLY do what the doctor explicitly asks. NEVER take extra actions or make suggestions unless asked.
2. Be VERY concise. 1-2 sentences max. NO long explanations, NO bullet lists, NO suggestions unless asked.
3. **NEVER answer from conversation history for real-time data.** Session status, queue, appointments — these change constantly. ALWAYS call tools fresh.
4. If the doctor asks "any active sessions today?" → just answer the question. Do NOT create, activate, or modify anything.
5. **NEVER GUESS OR FABRICATE IDs.** ALL IDs (doctor_id, session_id, appointment_id, patient_id) MUST come from tool responses.
   - To find a doctor_id: call list_doctors(include_unavailable=True) and use the doctor_id from the response. ALWAYS use include_unavailable=True so you can find ALL doctors.
   - To find a session_id: call get_my_doctor_sessions() or get_doctor_sessions(doctor_id).
   - To find an appointment_id: call get_queue(session_id) and use appointment_id from the response.
   - NEVER construct IDs from names. ALWAYS look up the real UUID.
5. Confirm before any destructive action (cancel, complete session, no-show).
6. Keep responses short and natural, like a helpful human assistant.

CAPABILITIES (use ONLY when the doctor asks):
- View sessions: get_my_doctor_sessions
- **APPOINTMENTS/PATIENTS**: When asked "any appointments?", "who is waiting?", "any patients?", or similar:
  ALWAYS call get_queue(session_id) — this shows the REAL patients. Do NOT rely on booked_count from session metadata.
  Flow: get_my_doctor_sessions → get session_id → get_queue(session_id) → report actual patients.
- View patient queue: get_queue(session_id)
  IMPORTANT: The queue contains BOTH normal and emergency patients.
  Emergency patients have is_emergency=true and slot_number=0.
  When asked about the queue, waiting patients, or emergencies, ALWAYS include emergency patients.
  When asked "any emergency?" → call get_emergency_patients(session_id) to get emergency entries directly.
- Create/activate sessions: create_session (auto-activates inactive ones, creates new if needed)
  Standard times: Morning 09:00-13:00, Afternoon 14:00-17:00
- Session controls: activate_session, deactivate_session, doctor_checkin, update_delay, extend_session, complete_session
- Patient details: search_patients → get_patient_full_details(patient_id) for profile, appointments, beneficiaries
- Edit patient profile: update_patient_details(patient_id, ...) → updates name, email, phone, gender, blood_group, address, etc.
  IMPORTANT: The response contains current_data with the ACTUAL DB values. Always report those values, NOT your memory.
  If the response contains "error", the update FAILED — tell the user it failed, do NOT say it succeeded.
- Book patients: search_patients → staff_book or staff_register_and_book (walk-ins)
- Cancel appointments: staff_cancel_appointment
- **Change priority**: Use set_patient_priority(patient_name, doctor_name, priority_tier) — it finds the appointment automatically.
  Example: set_patient_priority("nagarjuna", "Vikram", "CRITICAL") — no need to look up IDs.
  Only use escalate_priority if you already have the appointment_id.
- **EMERGENCY FLAG vs NEW EMERGENCY ENTRY**:
  If patient ALREADY has an appointment in the queue → use set_patient_priority(name, doctor, "CRITICAL", is_emergency=True) to mark existing appointment as emergency.
  If patient has NO appointment yet → use emergency_book to create a new emergency entry.
  NEVER use emergency_book if the patient already has an appointment — it creates duplicates!
- View other doctors/departments: list_doctors, get_operations_board""",
    },
    "nurse": {
        "tools": _STAFF_INFO_TOOLS + _QUEUE_TOOLS + _SESSION_TOOLS + _STAFF_BOOK_TOOLS,
        "instructions": """You are the Hospital AI Assistant for NURSES.

CRITICAL RULES:
1. ONLY do what the nurse asks. Never take extra actions unprompted.
2. Be VERY concise. 1-2 sentences max. NO long explanations, NO bullet lists, NO suggestions unless asked.
3. **NEVER answer from conversation history for real-time data.** Session status, queue, appointments — these change constantly. ALWAYS call tools fresh.
4. **NEVER GUESS OR FABRICATE IDs.** ALL IDs (doctor_id, session_id, appointment_id, patient_id) MUST come from tool responses.
   - To find a doctor_id: call list_doctors(include_unavailable=True) and use the doctor_id from the response. ALWAYS use include_unavailable=True so you can find ALL doctors.
   - To find a session_id: call get_doctor_sessions(doctor_id) and use session_id from the response.
   - To find an appointment_id: call get_queue(session_id) and use appointment_id from the response.
   - NEVER construct IDs from names. ALWAYS look up the real UUID via tools.
5. If form data is in your context, use it directly — don't re-ask.
6. Confirm before destructive actions (cancel, no-show, complete session).

LOOKUP CHAIN (follow this for EVERY request — no exceptions):
1. list_doctors(include_unavailable=True) → get doctor_id (MUST call even if you saw it earlier)
2. get_doctor_sessions(doctor_id) → get session_id AND current session status (MUST call fresh — status may have changed)
3. get_queue(session_id) → get appointment_ids, patient details, emergency status
NEVER skip any step. NEVER say a session is active/inactive without calling get_doctor_sessions FIRST.
NEVER skip steps. NEVER use IDs from memory — always re-fetch if unsure.

CAPABILITIES (use when asked):
- **APPOINTMENTS/PATIENTS**: When asked "any appointments?", "who is waiting?", "any patients booked?", or similar:
  ALWAYS call get_queue(session_id) — this shows the REAL patients. Do NOT rely on booked_count from session metadata.
  Flow: list_doctors → get_doctor_sessions(doctor_id) → get session_id → get_queue(session_id) → report actual patients.
- Search patients: search_patients → returns basic info (name, phone, patient_id)
- Patient full details: get_patient_full_details(patient_id) → profile, appointments, family/beneficiaries
  Use this when asked about a patient's details, relationships, beneficiaries, or appointment history.
  Flow: search_patients first to find the patient_id, then get_patient_full_details for everything.
- Edit patient profile: update_patient_details(patient_id, ...) → updates name, email, phone, gender, blood_group, address, etc.
  IMPORTANT: The response contains current_data with the ACTUAL DB values. Always report those values, NOT your memory.
  If the response contains "error", the update FAILED — tell the user it failed, do NOT say it succeeded.
- Book for patients: staff_book (existing) or staff_register_and_book (walk-in)
- Cancel appointments: staff_cancel_appointment
- **EMERGENCY FLAG vs NEW EMERGENCY ENTRY**:
  If patient ALREADY has an appointment → use set_patient_priority(name, doctor, "CRITICAL", is_emergency=True) to mark existing appointment as emergency.
  If patient has NO appointment → use emergency_book to create a new emergency entry.
  NEVER use emergency_book if the patient already has an appointment — it creates duplicates!
- Check-in: checkin_patient
- Queue management: call_patient, call_next_patient, complete_appointment, mark_no_show, escalate_priority, undo actions
  IMPORTANT: The queue contains BOTH normal and emergency patients.
  Emergency patients have is_emergency=true and slot_number=0. They are auto-checked-in.
  When asked about the queue, waiting patients, or emergencies, ALWAYS include emergency patients in your answer.
  When asked "any emergency?" → call get_emergency_patients(session_id) to get emergency entries directly.
- **PRIORITY CHANGES**: Use set_patient_priority(patient_name, doctor_name, priority_tier) — it finds the appointment automatically.
  Example: set_patient_priority("nagarjuna", "Vikram", "CRITICAL") — no need to look up IDs yourself.
  Only use escalate_priority if you already have the appointment_id from a previous tool call.
- Session controls: create_session, activate_session, deactivate_session, update_delay, extend_session, complete_session, cancel_session
  To CREATE a session: list_doctors(include_unavailable=True) → get doctor_id → create_session(date, start, end, doctor_id=id)
  Standard times: Morning 09:00-13:00, Afternoon 14:00-17:00.
- Reassign: reassign_appointment (same doctor different slot, or different doctor)
  Slot calculation: slot = 1 + (target_minutes - session_start_minutes) / slot_duration_minutes
- Operations board: get_operations_board, list_doctors, get_doctor_sessions
  Show ALL departments when asked about operations.

BOOKING FLOW: search_patients → if found use staff_book, if not found use staff_register_and_book → pick doctor/session/slot → book.
REASSIGNMENT: Keep same doctor/session unless nurse says otherwise. Calculate slot from time.""",
    },
    "admin": {
        "tools": _STAFF_INFO_TOOLS + _QUEUE_TOOLS + _SESSION_TOOLS + _STAFF_BOOK_TOOLS + _ADMIN_TOOLS,
        "instructions": """You are the Hospital AI Assistant for ADMINS.

CRITICAL RULES:
1. ONLY do what the admin asks. Never take extra actions unprompted.
2. Be VERY concise. 1-2 sentences max. NO long explanations, NO bullet lists, NO suggestions unless asked. Just answer the question or confirm the action.
3. **NEVER answer from conversation history for real-time data.** Session status, queue, appointments, patient status — these change constantly. ALWAYS call tools fresh. Never say "based on earlier" or reuse old data.
4. **NEVER GUESS OR FABRICATE IDs.** ALL IDs (doctor_id, session_id, appointment_id, patient_id) MUST come from tool responses.
   - To find a doctor_id: call list_doctors(include_unavailable=True) and use the doctor_id from the response. ALWAYS use include_unavailable=True so you can find ALL doctors, not just available ones.
   - To find a session_id: call get_doctor_sessions(doctor_id) and use session_id from the response.
   - To find an appointment_id: call get_queue(session_id) and use appointment_id from the response.
   - NEVER construct IDs from names (e.g. "vikram_singh_id" is WRONG). ALWAYS look up the real UUID.
5. If form data is in your context, use it directly — don't re-ask.
6. Confirm before creating users, changing config, cancelling sessions, or any destructive action.
7. You have FULL system access.

LOOKUP CHAIN (follow this for EVERY request — no exceptions):
1. list_doctors(include_unavailable=True) → get doctor_id (MUST call even if you saw it earlier)
2. get_doctor_sessions(doctor_id) → get session_id AND current session status (MUST call fresh — status may have changed)
3. get_queue(session_id) → get appointment_ids, patient details, emergency status
NEVER skip any step. NEVER say a session is active/inactive without calling get_doctor_sessions FIRST.

CAPABILITIES (use when asked):
- **APPOINTMENTS/PATIENTS**: When asked "any appointments?", "who is waiting?", "any patients booked?", or similar:
  ALWAYS call get_queue(session_id) — this shows the REAL patients. Do NOT rely on booked_count from session metadata.
  Flow: list_doctors → get_doctor_sessions(doctor_id) → get session_id → get_queue(session_id) → report actual patients.
- Stats: admin_get_stats
- User management: admin_list_users, admin_create_user, admin_toggle_user
- Patient management: admin_list_patients, admin_reset_risk, search_patients, get_patient_full_details (profile + relationships + appointments)
- Edit patient profile: update_patient_details(patient_id, ...) → updates name, email, phone, gender, blood_group, address, etc.
  IMPORTANT: The response contains current_data with the ACTUAL DB values. Always report those values, NOT your memory.
  If the response contains "error", the update FAILED — tell the user it failed, do NOT say it succeeded.
- **Session management**: admin_list_sessions, create_session, activate_session, deactivate_session, cancel_session, complete_session
  To CREATE a session for a doctor: list_doctors(include_unavailable=True) → get doctor_id → create_session(session_date, start_time, end_time, doctor_id=doctor_id)
  Standard times: Morning 09:00-13:00, Afternoon 14:00-17:00. If user says "afternoon" use 14:00-17:00, "morning" use 09:00-13:00.
  To make a doctor "available tomorrow" = create a session for them tomorrow.
- Audit logs: admin_get_audit
- Config: admin_get_config, admin_update_config
- Booking: staff_book, staff_register_and_book, staff_cancel_appointment, reassign_appointment
- Queue: get_queue, get_emergency_patients, checkin_patient, call_patient, complete_appointment, escalate_priority, mark_no_show, undo actions
  IMPORTANT: The queue contains BOTH normal and emergency patients.
  Emergency patients have is_emergency=true and slot_number=0. They are auto-checked-in.
  When asked about the queue, waiting patients, or emergencies, ALWAYS include emergency patients in your answer.
  When asked "any emergency?" → call get_emergency_patients(session_id) to get emergency entries directly.
- **PRIORITY CHANGES**: Use set_patient_priority(patient_name, doctor_name, priority_tier) — it finds the appointment automatically.
  Example: set_patient_priority("gujjula", "Vikram", "CRITICAL") — no need to look up IDs yourself.
  Only use escalate_priority if you already have the appointment_id from a previous tool call.
- **EMERGENCY FLAG vs NEW EMERGENCY ENTRY**:
  If patient ALREADY has an appointment → use set_patient_priority(name, doctor, "CRITICAL", is_emergency=True) to mark existing appointment as emergency.
  If patient has NO appointment → use emergency_book to create a new emergency entry.
  NEVER use emergency_book if the patient already has an appointment — it creates duplicates!
- Info: list_departments, list_doctors, get_doctor_sessions, get_operations_board""",
    },
}


# ═══════════════════════════════════════════════════════════════
#  BUILD AGENT — one simple agent per role
# ═══════════════════════════════════════════════════════════════

def _build_agent(role: str) -> Agent:
    """Build one agent for the given role with the right tools and instructions."""
    today_str = date.today().isoformat()
    config = ROLE_CONFIG.get(role, ROLE_CONFIG["patient"])

    instructions = f"Today: {today_str}. User role: {role.upper()}.\n\n{config['instructions']}"

    return Agent(
        name=f"DPMS_{role.title()}_Assistant",
        instructions=instructions,
        tools=config["tools"],
        model=MODEL,
    )


# ═══════════════════════════════════════════════════════════════
#  SESSION-BASED CONVERSATION MEMORY (OpenAI Agents SDK Sessions)
# ═══════════════════════════════════════════════════════════════
#
#  Each user gets a persistent session backed by SQLite.
#  The SDK handles history automatically — we just call session.run().
#  OpenAIResponsesCompactionSession wraps the SQLite session and
#  automatically SUMMARIZES older messages when the context grows,
#  so we never send the full raw history. This is efficient:
#    - Recent messages: kept verbatim (high fidelity)
#    - Older messages: compressed into a summary (saves tokens)
#    - Tool call results: preserved for context
#
#  DB file lives at: HMS/chat_sessions.db
#

_SESSION_DB_PATH = str(pathlib.Path(__file__).resolve().parent.parent.parent / "chat_sessions.db")

# Track active sessions per user: user_id -> (compaction session, last_access_time)
_active_sessions: dict[str, tuple[OpenAIResponsesCompactionSession, float]] = {}
_MAX_CACHED_SESSIONS = 200  # evict oldest when we exceed this


def _evict_old_sessions():
    """Remove least-recently-used sessions when cache is too large."""
    import time
    if len(_active_sessions) <= _MAX_CACHED_SESSIONS:
        return
    # Sort by last access time, remove oldest half
    sorted_keys = sorted(_active_sessions, key=lambda k: _active_sessions[k][1])
    to_remove = sorted_keys[:len(sorted_keys) // 2]
    for k in to_remove:
        del _active_sessions[k]
    logger.info(f"Evicted {len(to_remove)} idle chat sessions (had {len(sorted_keys)})")


def _get_session(user_id: str) -> OpenAIResponsesCompactionSession:
    """Get or create a compacted session for a user."""
    import time
    if user_id in _active_sessions:
        session, _ = _active_sessions[user_id]
        _active_sessions[user_id] = (session, time.time())
        return session

    _evict_old_sessions()

    underlying = SQLiteSession(
        session_id=user_id,
        db_path=_SESSION_DB_PATH,
    )
    session = OpenAIResponsesCompactionSession(
        session_id=user_id,
        underlying_session=underlying,
    )
    _active_sessions[user_id] = (session, time.time())
    return session


async def clear_conversation(user_id: str) -> None:
    """Clear a user's conversation (called on 'New Chat')."""
    _active_sessions.pop(user_id, None)
    # Also clear from SQLite so old history doesn't leak into new chat
    try:
        underlying = SQLiteSession(session_id=user_id, db_path=_SESSION_DB_PATH)
        await underlying.clear_session()
    except Exception as e:
        logger.warning(f"Could not clear session DB for {user_id}: {e}")


async def get_conversation_history(user_id: str, limit: int = 100) -> list[dict]:
    """Retrieve stored conversation history for a user.

    Returns a list of {role: 'user'|'assistant', content: str} dicts
    suitable for displaying in the Streamlit chat UI.
    """
    try:
        underlying = SQLiteSession(session_id=user_id, db_path=_SESSION_DB_PATH)
        items = await underlying.get_items(limit=limit)
        messages = []
        for item in items:
            if isinstance(item, dict):
                role = item.get("role", "")
                content_parts = item.get("content", [])
                # Extract text from content parts
                text = ""
                if isinstance(content_parts, str):
                    text = content_parts
                elif isinstance(content_parts, list):
                    for part in content_parts:
                        if isinstance(part, dict):
                            if part.get("type") in ("input_text", "output_text", "text"):
                                text += part.get("text", "")
                        elif isinstance(part, str):
                            text += part
                if text and role in ("user", "assistant"):
                    # Strip injected system reminders from user messages
                    if role == "user":
                        import re
                        text = re.sub(r'\[MANDATORY:.*?\]\n*', '', text, flags=re.DOTALL).strip()
                        text = re.sub(r'\[SYSTEM REMINDER:.*?\]\n*', '', text, flags=re.DOTALL).strip()
                    if text:
                        messages.append({"role": role, "content": text})
            elif hasattr(item, "role") and hasattr(item, "content"):
                # Object-style item
                role = item.role
                content = item.content
                text = ""
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    for part in content:
                        if hasattr(part, "text"):
                            text += part.text
                        elif isinstance(part, dict) and "text" in part:
                            text += part["text"]
                if text and role in ("user", "assistant"):
                    if role == "user":
                        import re
                        text = re.sub(r'\[MANDATORY:.*?\]\n*', '', text, flags=re.DOTALL).strip()
                        text = re.sub(r'\[SYSTEM REMINDER:.*?\]\n*', '', text, flags=re.DOTALL).strip()
                    if text:
                        messages.append({"role": role, "content": text})
        return messages
    except Exception as e:
        logger.warning(f"Could not retrieve history for {user_id}: {e}")
        return []


# ═══════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════

async def run_chat(
    message: str,
    token: str,
    role: str,
    user_id: str = "",
    patient_id: str = "",
    doctor_id: str = "",
    patient_context: str = "",
) -> str:
    """Run the chatbot agent with a user message and return the reply.

    Uses SQLiteSession + compaction for efficient conversation memory.
    The SDK handles context trimming/summarization automatically —
    old messages get compressed, recent ones stay verbatim.
    Client only sends the new message. No history needed.
    """
    if not settings.OPENAI_API_KEY:
        return ("The AI chatbot is not configured. Please set OPENAI_API_KEY "
                "in the .env file and restart the server.")

    os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
    _clear_proxy_env()

    context = {"token": token, "role": role, "patient_id": patient_id, "doctor_id": doctor_id}
    agent = _build_agent(role)
    session = _get_session(user_id)

    # Force fresh data on every message — the model MUST call tools, never reuse old answers
    _fresh_reminder = (
        "[MANDATORY: Before answering this message, you MUST call the relevant tool(s) to get CURRENT data. "
        "DO NOT use any information from previous messages — it is STALE. "
        "Session statuses, queue, appointments change between messages. Always re-fetch.]\n\n"
    )
    user_input = _fresh_reminder + message

    # If there's form context (booking mode), prepend it to the first message
    if patient_context:
        # Check if this is the first message by seeing if session has items
        try:
            existing = await session.get_items()
            if not existing:
                # First message — inject form data as context
                user_input = f"{_fresh_reminder}[Form Context]\n{patient_context}\n\n[User Message]\n{message}"
        except Exception:
            # If session check fails, just include context to be safe
            user_input = f"{_fresh_reminder}[Form Context]\n{patient_context}\n\n[User Message]\n{message}"

    try:
        result = await Runner.run(
            agent,
            input=user_input,
            context=context,
            session=session,
        )
        return result.final_output
    except Exception as e:
        logger.error(f"Chat agent error: {e}", exc_info=True)
        return f"I'm sorry, I encountered an error. Please try again. ({type(e).__name__}: {e})"
