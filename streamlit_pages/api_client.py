"""
API Client — thin wrapper around httpx to call the FastAPI backend.

Every Streamlit page imports this to make authenticated API calls.
Handles: token storage in session_state, auto-refresh, error formatting.
"""
import httpx
import streamlit as st

BASE_URL = "http://localhost:8000/api"
TIMEOUT = 10.0


def _headers() -> dict:
    """Attach JWT access token if logged in."""
    token = st.session_state.get("access_token")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


# ─── Auth ─────────────────────────────────────────────────────

def login(email: str, password: str) -> dict:
    """POST /auth/login — OAuth2 form data."""
    r = httpx.post(
        f"{BASE_URL}/auth/login",
        data={"username": email, "password": password},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def register(payload: dict) -> dict:
    """POST /auth/register — JSON body."""
    r = httpx.post(f"{BASE_URL}/auth/register", json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_me() -> dict:
    """GET /auth/me — current user profile."""
    r = httpx.get(f"{BASE_URL}/auth/me", headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def refresh_token(refresh_tok: str) -> dict:
    """POST /auth/refresh — get new access token."""
    r = httpx.post(
        f"{BASE_URL}/auth/refresh",
        json={"refresh_token": refresh_tok},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


# ─── Patients ─────────────────────────────────────────────────

def get_my_profile() -> dict:
    r = httpx.get(f"{BASE_URL}/patients/me", headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def update_my_profile(payload: dict) -> dict:
    r = httpx.put(f"{BASE_URL}/patients/me", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_my_relationships() -> list:
    r = httpx.get(f"{BASE_URL}/patients/me/relationships", headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def add_relationship(payload: dict) -> dict:
    r = httpx.post(f"{BASE_URL}/patients/me/relationships", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def search_patients(query: str) -> list:
    """GET /patients/search?q=... — staff search patients by name/phone."""
    r = httpx.get(f"{BASE_URL}/patients/search", params={"q": query}, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


# ─── Doctors ──────────────────────────────────────────────────

def list_doctors(specialization: str = "") -> list:
    params = {}
    if specialization:
        params["specialization"] = specialization
    r = httpx.get(f"{BASE_URL}/doctors/", params=params, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_doctor(doctor_id: str) -> dict:
    r = httpx.get(f"{BASE_URL}/doctors/{doctor_id}", headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_doctor_sessions(doctor_id: str, from_date: str = "", to_date: str = "", include_all: bool = False) -> list:
    params = {}
    if from_date:
        params["date_from"] = from_date
    if to_date:
        params["date_to"] = to_date
    if include_all:
        params["include_all"] = "true"
    r = httpx.get(f"{BASE_URL}/doctors/{doctor_id}/sessions", params=params, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_all_doctor_sessions(doctor_id: str, from_date: str = "", to_date: str = "") -> list:
    """Get ALL sessions (active + completed + cancelled) for doctor dashboard."""
    params = {}
    if from_date:
        params["date_from"] = from_date
    if to_date:
        params["date_to"] = to_date
    r = httpx.get(f"{BASE_URL}/doctors/{doctor_id}/all-sessions", params=params, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


# ─── Appointments ─────────────────────────────────────────────

def book_appointment(payload: dict) -> dict:
    r = httpx.post(f"{BASE_URL}/appointments/book", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def cancel_appointment(payload: dict) -> dict:
    r = httpx.post(f"{BASE_URL}/appointments/cancel", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_my_appointments() -> dict:
    """Returns list of appointments (API returns list, we wrap it)."""
    r = httpx.get(f"{BASE_URL}/appointments/my", headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    # API returns a plain list, wrap it for consistency
    if isinstance(data, list):
        return {"appointments": data, "total": len(data)}
    return data


def get_appointment(appointment_id: str) -> dict:
    r = httpx.get(f"{BASE_URL}/appointments/{appointment_id}", headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def emergency_book(payload: dict) -> dict:
    r = httpx.post(f"{BASE_URL}/appointments/emergency", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


# ─── Session Management ──────────────────────────────────────

def doctor_checkin(payload: dict) -> dict:
    r = httpx.post(f"{BASE_URL}/sessions/checkin", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def update_delay(payload: dict) -> dict:
    r = httpx.post(f"{BASE_URL}/sessions/update-delay", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def overtime_window(payload: dict) -> dict:
    r = httpx.post(f"{BASE_URL}/sessions/overtime-window", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def extend_session(payload: dict) -> dict:
    r = httpx.post(f"{BASE_URL}/sessions/extend", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def complete_session(payload: dict) -> dict:
    r = httpx.post(f"{BASE_URL}/sessions/complete-session", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def activate_session(payload: dict) -> dict:
    """POST /sessions/activate — set inactive → active."""
    r = httpx.post(f"{BASE_URL}/sessions/activate", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def deactivate_session(payload: dict) -> dict:
    """POST /sessions/deactivate — set active → inactive (blocks if patient in progress)."""
    r = httpx.post(f"{BASE_URL}/sessions/deactivate", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def cancel_session(payload: dict) -> dict:
    r = httpx.post(f"{BASE_URL}/sessions/cancel-session", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


# ─── Queue ────────────────────────────────────────────────────

def get_queue(session_id: str) -> dict:
    r = httpx.get(f"{BASE_URL}/queue/{session_id}", headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def checkin_patient(payload: dict) -> dict:
    r = httpx.post(f"{BASE_URL}/queue/checkin", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def call_patient(payload: dict) -> dict:
    """POST /queue/call-patient — call a specific checked-in patient to the doctor."""
    r = httpx.post(f"{BASE_URL}/queue/call-patient", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def call_next(payload: dict) -> dict:
    r = httpx.post(f"{BASE_URL}/queue/next", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def escalate_priority(payload: dict) -> dict:
    r = httpx.post(f"{BASE_URL}/queue/escalate", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def complete_appointment(payload: dict) -> dict:
    r = httpx.post(f"{BASE_URL}/queue/complete", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def undo_checkin(payload: dict) -> dict:
    r = httpx.post(f"{BASE_URL}/queue/undo-checkin", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def set_duration(payload: dict) -> dict:
    r = httpx.post(f"{BASE_URL}/queue/set-duration", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def mark_no_shows(payload: dict) -> dict:
    r = httpx.post(f"{BASE_URL}/queue/no-shows", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def mark_single_noshow(payload: dict) -> dict:
    """POST /queue/no-show-single — mark one patient as no-show."""
    r = httpx.post(f"{BASE_URL}/queue/no-show-single", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def undo_send(payload: dict) -> dict:
    """POST /queue/undo-send — reverse send-to-doctor (in_progress → checked_in)."""
    r = httpx.post(f"{BASE_URL}/queue/undo-send", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def undo_complete(payload: dict) -> dict:
    """POST /queue/undo-complete — reverse completion (completed → in_progress)."""
    r = httpx.post(f"{BASE_URL}/queue/undo-complete", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def undo_noshow(payload: dict) -> dict:
    """POST /queue/undo-noshow — reverse no-show mark (no_show → booked)."""
    r = httpx.post(f"{BASE_URL}/queue/undo-noshow", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def undo_cancel(payload: dict) -> dict:
    """POST /appointments/undo-cancel — reverse patient cancellation (cancelled → booked)."""
    r = httpx.post(f"{BASE_URL}/appointments/undo-cancel", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def list_departments() -> list:
    """GET /appointments/departments — unique specialization list for dropdowns."""
    r = httpx.get(f"{BASE_URL}/appointments/departments", headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_operations_board(date_str: str = "", department: str = "") -> dict:
    """GET /appointments/board — staff operations board grouped by dept → doctor."""
    params = {}
    if date_str:
        params["date"] = date_str
    if department:
        params["department"] = department
    r = httpx.get(f"{BASE_URL}/appointments/board", params=params, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def reassign_appointment(payload: dict) -> dict:
    """POST /appointments/reassign — move appointment to another doctor's session."""
    r = httpx.post(f"{BASE_URL}/appointments/reassign", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def staff_book(payload: dict) -> dict:
    """POST /appointments/staff-book — nurse books on behalf of a patient."""
    r = httpx.post(f"{BASE_URL}/appointments/staff-book", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def staff_register_book(payload: dict) -> dict:
    """POST /appointments/staff-register-book — nurse registers new patient and books."""
    r = httpx.post(f"{BASE_URL}/appointments/staff-register-book", json=payload, headers=_headers(), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()
