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
        async with httpx.AsyncClient(timeout=20.0) as client:
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
    return _j(await _api("GET", "/appointments/departments", ctx.context["token"]))


@function_tool
async def list_doctors(ctx: RunContextWrapper, specialization: str = "") -> str:
    """List doctors, optionally filtered by specialization.
    Args:
        specialization: e.g. 'Cardiology'. Empty = all doctors.
    """
    params = {"specialization": specialization} if specialization else {}
    result = await _api("GET", "/doctors", ctx.context["token"], params=params)
    if isinstance(result, list):
        return _j([{
            "doctor_id": d.get("doctor_id") or d.get("id"),
            "name": d.get("full_name") or d.get("name"),
            "specialization": d.get("specialization"),
            "qualification": d.get("qualification"),
            "consultation_fee": d.get("consultation_fee"),
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
    """Get available sessions for a doctor (today onward).
    Args:
        doctor_id: UUID of the doctor.
    """
    params = {"date_from": date.today().isoformat()}
    result = await _api("GET", f"/doctors/{doctor_id}/sessions", ctx.context["token"], params=params)
    if isinstance(result, list):
        return _j([{
            "session_id": s.get("session_id") or s.get("id"),
            "date": s.get("session_date"), "start": s.get("start_time"), "end": s.get("end_time"),
            "status": s.get("status"),
            "available": s.get("total_slots", 0) - s.get("booked_count", 0),
            "total_slots": s.get("total_slots"), "booked": s.get("booked_count"),
        } for s in result])
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
async def checkin_patient(ctx: RunContextWrapper, appointment_id: str) -> str:
    """Check in a patient who has arrived at the clinic.
    Args:
        appointment_id: UUID of the appointment.
    """
    return _j(await _api("POST", "/queue/checkin", ctx.context["token"],
                         payload={"appointment_id": appointment_id}))


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
async def escalate_priority(ctx: RunContextWrapper, appointment_id: str, reason: str = "") -> str:
    """Escalate a patient's priority in the queue.
    Args:
        appointment_id: UUID of the appointment.
        reason: Reason for escalation.
    """
    payload = {"appointment_id": appointment_id}
    if reason:
        payload["reason"] = reason
    return _j(await _api("POST", "/queue/escalate", ctx.context["token"], payload=payload))


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
async def extend_session(ctx: RunContextWrapper, session_id: str, extend_minutes: int) -> str:
    """Extend a session beyond scheduled end time.
    Args:
        session_id: UUID of the session.
        extend_minutes: Minutes to extend by.
    """
    return _j(await _api("POST", "/sessions/extend", ctx.context["token"],
                         payload={"session_id": session_id, "extend_minutes": extend_minutes}))


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
async def emergency_book(ctx: RunContextWrapper, session_id: str, slot_number: int, patient_id: str, reason: str) -> str:
    """Emergency booking override — forces patient into priority position.
    Args:
        session_id: UUID of session.
        slot_number: Slot number.
        patient_id: UUID of patient.
        reason: Emergency reason (min 5 chars).
    """
    return _j(await _api("POST", "/appointments/emergency", ctx.context["token"],
                         payload={"session_id": session_id, "slot_number": slot_number,
                                  "patient_id": patient_id, "reason": reason}))


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
    return _j(await _api("POST", "/appointments/staff-register-book", ctx.context["token"], payload=payload))


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

_INFO_TOOLS = [list_departments, list_doctors, get_doctor_details, get_doctor_sessions, get_operations_board]

_PATIENT_TOOLS = [book_appointment, cancel_appointment, undo_cancel_appointment,
                  get_my_appointments, get_my_profile, get_my_relationships,
                  update_family_member]

_QUEUE_TOOLS = [get_queue, checkin_patient, call_patient, call_next_patient,
                complete_appointment, mark_no_show, escalate_priority,
                set_appointment_duration, undo_checkin, undo_send_to_doctor,
                undo_complete_appointment, undo_no_show]

_SESSION_TOOLS = [activate_session, deactivate_session, doctor_checkin,
                  update_delay, set_overtime, extend_session,
                  complete_session, cancel_session]

_STAFF_BOOK_TOOLS = [search_patients, staff_book, staff_register_and_book,
                     emergency_book, reassign_appointment]

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
You help patients do everything their dashboard can do, via natural conversation:
- Browse doctors and departments, check availability
- Book appointments (find doctor → pick session → pick slot → book)
- View, cancel, or undo-cancel their appointments
- View their profile and family members with FULL details
- Update family member details (name, phone, blood group, relationship, etc.)

RULES:
- Use tools to get REAL data — never guess doctors, sessions, or IDs
- Confirm before booking or cancelling
- Never provide medical diagnoses — only help with logistics
- Keep responses concise and friendly
- When a patient describes symptoms, look up matching departments then find doctors in that department
- When asked about family members, use get_my_relationships to fetch their details.
  The response includes full beneficiary info: beneficiary_name, beneficiary_phone,
  beneficiary_gender, beneficiary_age, beneficiary_blood_group, beneficiary_date_of_birth,
  beneficiary_abha_id, beneficiary_address, beneficiary_email,
  beneficiary_emergency_contact_name, beneficiary_emergency_contact_phone.
  Always show ALL available details when asked — never say "not available" if the data is in the response.""",
    },
    "doctor": {
        "tools": _INFO_TOOLS + _QUEUE_TOOLS + _SESSION_TOOLS,
        "instructions": """You are the Hospital AI Assistant for DOCTORS.
You help doctors do everything their dashboard can do, via natural conversation:
- View and manage their patient queue (call next, call specific, complete, no-show, undo)
- Session controls (activate, check-in, set delay, extend, complete, deactivate)
- View operations board and schedule
- Look up doctor/department info

RULES:
- Use tools to get REAL data
- Confirm before destructive actions (complete session, no-show)
- Show queue status clearly after each action
- You are logged in as a DOCTOR, not a patient""",
    },
    "nurse": {
        "tools": _INFO_TOOLS + _QUEUE_TOOLS + _SESSION_TOOLS + _STAFF_BOOK_TOOLS,
        "instructions": """You are the Hospital AI Assistant for NURSES.
You help nurses do everything their dashboard can do, via natural conversation:
- Search patients by name or phone
- Book appointments on behalf of patients (existing or walk-in)
- Emergency bookings
- Check in patients, manage the queue (call, complete, no-show, undo)
- Session controls (activate, deactivate, delay)
- View operations board for ALL departments
- Reassign appointments (change time or change doctor)

IF form data is provided in your context (Patient Name, Phone, etc.):
  DO NOT re-ask for that info. USE IT DIRECTLY.
  When the user says "proceed" or "yes" or "book", START WORKING with the tools.

BOOKING WORKFLOW:
1. search_patients with patient name/phone
2. If found → get patient_id
3. If NOT found → use staff_register_and_book
4. list_doctors for the department → get_doctor_sessions → find slots
5. Show options briefly, confirm, then book

REASSIGNMENT WORKFLOW:
- When user says "reassign to X o'clock" → keep the SAME doctor and session unless they say otherwise
- Calculate slot number: slot = 1 + (target_hour - session_start_hour) * (60 / slot_duration_minutes)
  Example: session 09:00-13:00 with 15-min slots → 11:00 = slot 9
- Use the SAME session_id if just changing time
- Only suggest a DIFFERENT doctor if the user explicitly asks for one

OPERATIONS BOARD:
- Always show ALL departments (Cardiology, General Medicine, Pediatrics, etc.)
- Use list_doctors to get all doctors, then get_doctor_sessions for each
- Do NOT skip departments just because they have no bookings

RULES:
- Use tools to get REAL data — never guess
- You are a NURSE acting ON BEHALF of patients
- Be efficient and concise
- Show ALL departments when asked about operations""",
    },
    "admin": {
        "tools": _INFO_TOOLS + _QUEUE_TOOLS + _SESSION_TOOLS + _STAFF_BOOK_TOOLS + _ADMIN_TOOLS,
        "instructions": """You are the Hospital AI Assistant for ADMINS.
You help admins do everything their dashboard can do, via natural conversation:
- Dashboard stats (today's numbers)
- User management (list, create staff, activate/deactivate)
- Patient management (search, risk scores)
- Session management (list, cancel entire sessions)
- Audit logs
- System configuration (slot duration, clinic hours)
- Book on behalf of patients, emergency bookings
- Queue management

IF form data is provided in your context (Patient Name, Phone, etc.):
  DO NOT re-ask for that info. USE IT DIRECTLY.
  When the admin says "proceed" or "yes", START WORKING IMMEDIATELY with the tools.

RULES:
- Use tools to get REAL data
- Confirm before creating users, changing config, or cancelling sessions
- Provide clear summaries
- You have FULL system access
- NEVER re-ask for info already in the form context""",
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

# Track active sessions per user: user_id -> compaction session
_active_sessions: dict[str, OpenAIResponsesCompactionSession] = {}


def _get_session(user_id: str) -> OpenAIResponsesCompactionSession:
    """Get or create a compacted session for a user."""
    if user_id not in _active_sessions:
        underlying = SQLiteSession(
            session_id=user_id,
            db_path=_SESSION_DB_PATH,
        )
        _active_sessions[user_id] = OpenAIResponsesCompactionSession(
            session_id=user_id,
            underlying_session=underlying,
        )
    return _active_sessions[user_id]


async def clear_conversation(user_id: str) -> None:
    """Clear a user's conversation (called on 'New Chat')."""
    if user_id in _active_sessions:
        del _active_sessions[user_id]
    # Also clear from SQLite so old history doesn't leak into new chat
    try:
        underlying = SQLiteSession(session_id=user_id, db_path=_SESSION_DB_PATH)
        await underlying.clear_session()
    except Exception as e:
        logger.warning(f"Could not clear session DB for {user_id}: {e}")


# ═══════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════

async def run_chat(
    message: str,
    token: str,
    role: str,
    user_id: str = "",
    patient_id: str = "",
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

    context = {"token": token, "role": role, "patient_id": patient_id}
    agent = _build_agent(role)
    session = _get_session(user_id)

    # If there's form context (booking mode), prepend it to the first message
    user_input = message
    if patient_context:
        # Check if this is the first message by seeing if session has items
        try:
            existing = await session.get_items()
            if not existing:
                # First message — inject form data as context
                user_input = f"[Form Context]\n{patient_context}\n\n[User Message]\n{message}"
        except Exception:
            # If session check fails, just include context to be safe
            user_input = f"[Form Context]\n{patient_context}\n\n[User Message]\n{message}"

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
