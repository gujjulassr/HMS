"""
API Client — thin wrapper around httpx to call the FastAPI backend.

Every Streamlit page imports this to make authenticated API calls.
Handles: token storage in session_state, auto-refresh, error formatting.
"""
import httpx
import streamlit as st

BASE_URL = "http://localhost:8000/api"
TIMEOUT = 10.0


def _raise_api_error(r: httpx.Response):
    """Extract the API error detail and raise a clean exception."""
    try:
        detail = r.json().get("detail", r.text)
    except Exception:
        detail = r.text
    raise Exception(f"{r.status_code}: {detail}")


def _headers() -> dict:
    """Attach JWT access token if logged in."""
    token = st.session_state.get("access_token")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def _try_refresh() -> bool:
    """Attempt to refresh the access token. Returns True on success."""
    ref_tok = st.session_state.get("refresh_token")
    if not ref_tok:
        return False
    try:
        r = httpx.post(
            f"{BASE_URL}/auth/refresh",
            json={"refresh_token": ref_tok},
            timeout=TIMEOUT,
        )
        if r.status_code == 200:
            data = r.json()
            st.session_state.access_token = data["access_token"]
            st.session_state.refresh_token = data.get("refresh_token", ref_tok)
            return True
    except Exception:
        pass
    return False


def _auto_logout():
    """Clear session state so next rerun shows login page."""
    for k in ("access_token", "refresh_token", "user", "patient"):
        st.session_state[k] = None
    st.session_state.page = "login"


def _request(method: str, url: str, **kwargs) -> httpx.Response:
    """
    Make an authenticated request with auto-refresh on 401.
    If refresh also fails, clears session and raises so callers see the error.
    """
    kwargs.setdefault("headers", _headers())
    kwargs.setdefault("timeout", TIMEOUT)
    kwargs.setdefault("follow_redirects", True)
    r = httpx.request(method, url, **kwargs)
    if r.status_code == 401 and _try_refresh():
        # Refresh worked — retry with new token
        kwargs["headers"] = _headers()
        r = httpx.request(method, url, **kwargs)
    if r.status_code == 401:
        # Both token and refresh failed — force logout
        _auto_logout()
        # Raise a clear error instead of st.rerun() (which gets caught by except blocks)
        raise httpx.HTTPStatusError(
            "Session expired — please log in again.",
            request=r.request,
            response=r,
        )
    return r


# ─── Auth ─────────────────────────────────────────────────────

def login(email: str, password: str) -> dict:
    """POST /auth/login — OAuth2 form data."""
    r = httpx.post(
        f"{BASE_URL}/auth/login",
        data={"username": email, "password": password},
        timeout=TIMEOUT,
    )

    # Check status first, THEN read the detail from JSON


    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def register(payload: dict) -> dict:
    """POST /auth/register — JSON body."""
    r = httpx.post(f"{BASE_URL}/auth/register", json=payload, timeout=TIMEOUT)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def get_me() -> dict:
    """GET /auth/me — current user profile."""
    r = _request("GET", f"{BASE_URL}/auth/me")
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def refresh_token(refresh_tok: str) -> dict:
    """POST /auth/refresh — get new access token."""
    r = httpx.post(
        f"{BASE_URL}/auth/refresh",
        json={"refresh_token": refresh_tok},
        timeout=TIMEOUT,
    )
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


# ─── Patients ─────────────────────────────────────────────────

def get_my_profile() -> dict:
    r = _request("GET", f"{BASE_URL}/patients/me")
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def update_my_profile(payload: dict) -> dict:
    r = _request("PUT", f"{BASE_URL}/patients/me", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def get_my_relationships() -> list:
    r = _request("GET", f"{BASE_URL}/patients/me/relationships")
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def add_relationship(payload: dict) -> dict:
    r = _request("POST", f"{BASE_URL}/patients/me/relationships", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def find_beneficiary(abha_id: str) -> list:
    """GET /patients/me/find-beneficiary?abha_id=... — patient searches by ABHA/UHID."""
    r = _request("GET", f"{BASE_URL}/patients/me/find-beneficiary", params={"abha_id": abha_id})
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def add_family_member(payload: dict) -> dict:
    """POST /patients/me/add-family — register new family member + auto-link."""
    r = _request("POST", f"{BASE_URL}/patients/me/add-family", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def update_family_member(relationship_id: str, payload: dict) -> dict:
    """PUT /patients/me/relationships/{id}/beneficiary — edit family member details."""
    r = _request("PUT", f"{BASE_URL}/patients/me/relationships/{relationship_id}/beneficiary", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def search_patients(query: str) -> list:
    """GET /patients/search?q=... — staff search patients by name/phone."""
    r = _request("GET", f"{BASE_URL}/patients/search", params={"q": query})
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


# ─── Doctors ──────────────────────────────────────────────────

def list_doctors(specialization: str = "") -> list:
    params = {}
    if specialization:
        params["specialization"] = specialization
    r = _request("GET", f"{BASE_URL}/doctors/", params=params)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def get_doctor(doctor_id: str) -> dict:
    r = _request("GET", f"{BASE_URL}/doctors/{doctor_id}")
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def get_doctor_sessions(doctor_id: str, from_date: str = "", to_date: str = "", include_all: bool = False) -> list:
    params = {}
    if from_date:
        params["date_from"] = from_date
    if to_date:
        params["date_to"] = to_date
    if include_all:
        params["include_all"] = "true"
    r = _request("GET", f"{BASE_URL}/doctors/{doctor_id}/sessions", params=params)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def get_all_doctor_sessions(doctor_id: str, from_date: str = "", to_date: str = "") -> list:
    """Get ALL sessions (active + completed + cancelled) for doctor dashboard."""
    params = {}
    if from_date:
        params["date_from"] = from_date
    if to_date:
        params["date_to"] = to_date
    r = _request("GET", f"{BASE_URL}/doctors/{doctor_id}/all-sessions", params=params)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


# ─── Appointments ─────────────────────────────────────────────

def book_appointment(payload: dict) -> dict:
    r = _request("POST", f"{BASE_URL}/appointments/book", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def cancel_appointment(payload: dict) -> dict:
    r = _request("POST", f"{BASE_URL}/appointments/cancel", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def staff_cancel_appointment(payload: dict) -> dict:
    """Cancel appointment as nurse/admin/doctor (no patient role needed)."""
    r = _request("POST", f"{BASE_URL}/appointments/staff-cancel", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def get_my_appointments() -> dict:
    """Returns list of appointments (API returns list, we wrap it)."""
    r = _request("GET", f"{BASE_URL}/appointments/my")
    r.raise_for_status()
    data = r.json()
    # API returns a plain list, wrap it for consistency
    if isinstance(data, list):
        return {"appointments": data, "total": len(data)}
    return data


def get_appointment(appointment_id: str) -> dict:
    r = _request("GET", f"{BASE_URL}/appointments/{appointment_id}")
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def emergency_book(payload: dict) -> dict:
    r = _request("POST", f"{BASE_URL}/appointments/emergency", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def quick_register_patient(payload: dict) -> dict:
    r = _request("POST", f"{BASE_URL}/admin/quick-register", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


# ─── Session Management ──────────────────────────────────────

def doctor_checkin(payload: dict) -> dict:
    r = _request("POST", f"{BASE_URL}/sessions/checkin", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def update_delay(payload: dict) -> dict:
    r = _request("POST", f"{BASE_URL}/sessions/update-delay", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def overtime_window(payload: dict) -> dict:
    r = _request("POST", f"{BASE_URL}/sessions/overtime-window", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def extend_session(payload: dict) -> dict:
    r = _request("POST", f"{BASE_URL}/sessions/extend", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def complete_session(payload: dict) -> dict:
    r = _request("POST", f"{BASE_URL}/sessions/complete-session", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def activate_session(payload: dict) -> dict:
    """POST /sessions/activate — set inactive → active."""
    r = _request("POST", f"{BASE_URL}/sessions/activate", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def deactivate_session(payload: dict) -> dict:
    """POST /sessions/deactivate — set active → inactive (blocks if patient in progress)."""
    r = _request("POST", f"{BASE_URL}/sessions/deactivate", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def cancel_session(payload: dict) -> dict:
    r = _request("POST", f"{BASE_URL}/sessions/cancel-session", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


# ─── Queue ────────────────────────────────────────────────────

def get_queue(session_id: str) -> dict:
    r = _request("GET", f"{BASE_URL}/queue/{session_id}")
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def checkin_patient(payload: dict) -> dict:
    r = _request("POST", f"{BASE_URL}/queue/checkin", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def call_patient(payload: dict) -> dict:
    """POST /queue/call-patient — call a specific checked-in patient to the doctor."""
    r = _request("POST", f"{BASE_URL}/queue/call-patient", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def call_next(payload: dict) -> dict:
    r = _request("POST", f"{BASE_URL}/queue/next", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def escalate_priority(payload: dict) -> dict:
    r = _request("POST", f"{BASE_URL}/queue/escalate", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def complete_appointment(payload: dict) -> dict:
    r = _request("POST", f"{BASE_URL}/queue/complete", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def undo_checkin(payload: dict) -> dict:
    r = _request("POST", f"{BASE_URL}/queue/undo-checkin", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def set_duration(payload: dict) -> dict:
    r = _request("POST", f"{BASE_URL}/queue/set-duration", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def mark_no_shows(payload: dict) -> dict:
    r = _request("POST", f"{BASE_URL}/queue/no-shows", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def mark_single_noshow(payload: dict) -> dict:
    """POST /queue/no-show-single — mark one patient as no-show."""
    r = _request("POST", f"{BASE_URL}/queue/no-show-single", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def undo_send(payload: dict) -> dict:
    """POST /queue/undo-send — reverse send-to-doctor (in_progress → checked_in)."""
    r = _request("POST", f"{BASE_URL}/queue/undo-send", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def undo_complete(payload: dict) -> dict:
    """POST /queue/undo-complete — reverse completion (completed → in_progress)."""
    r = _request("POST", f"{BASE_URL}/queue/undo-complete", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def undo_noshow(payload: dict) -> dict:
    """POST /queue/undo-noshow — reverse no-show mark (no_show → booked)."""
    r = _request("POST", f"{BASE_URL}/queue/undo-noshow", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def undo_cancel(payload: dict) -> dict:
    """POST /appointments/undo-cancel — reverse patient cancellation (cancelled → booked)."""
    r = _request("POST", f"{BASE_URL}/appointments/undo-cancel", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def list_departments() -> list:
    """GET /appointments/departments — unique specialization list for dropdowns."""
    r = _request("GET", f"{BASE_URL}/appointments/departments")
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def get_operations_board(date_str: str = "", department: str = "") -> dict:
    """GET /appointments/board — staff operations board grouped by dept → doctor."""
    params = {}
    if date_str:
        params["date"] = date_str
    if department:
        params["department"] = department
    r = _request("GET", f"{BASE_URL}/appointments/board", params=params)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def reassign_appointment(payload: dict) -> dict:
    """POST /appointments/reassign — move appointment to another doctor's session."""
    r = _request("POST", f"{BASE_URL}/appointments/reassign", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def staff_book(payload: dict) -> dict:
    """POST /appointments/staff-book — nurse books on behalf of a patient."""
    r = _request("POST", f"{BASE_URL}/appointments/staff-book", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def staff_register_book(payload: dict) -> dict:
    """POST /appointments/staff-register-book — nurse registers new patient and books."""
    r = _request("POST", f"{BASE_URL}/appointments/staff-register-book", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


# ─── Admin ────────────────────────────────────────────────

def admin_stats() -> dict:
    """GET /admin/stats — dashboard stats."""
    r = _request("GET", f"{BASE_URL}/admin/stats")
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def admin_list_users(role: str = "", include_inactive: bool = False) -> list:
    """GET /admin/users — list all users."""
    params = {}
    if role:
        params["role"] = role
    if include_inactive:
        params["include_inactive"] = "true"
    r = _request("GET", f"{BASE_URL}/admin/users", params=params)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def admin_create_user(payload: dict) -> dict:
    """POST /admin/users — create staff user."""
    r = _request("POST", f"{BASE_URL}/admin/users", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def admin_update_user(user_id: str, payload: dict) -> dict:
    """PUT /admin/users/{id} — update user."""
    r = _request("PUT", f"{BASE_URL}/admin/users/{user_id}", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def admin_toggle_user(user_id: str) -> dict:
    """PUT /admin/users/{id}/toggle — activate/deactivate."""
    r = _request("PUT", f"{BASE_URL}/admin/users/{user_id}/toggle")
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def admin_list_departments() -> list:
    """GET /admin/departments — all unique departments."""
    r = _request("GET", f"{BASE_URL}/admin/departments")
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def admin_list_doctors(specialization: str = "") -> list:
    """GET /admin/doctors — all doctors with details."""
    params = {}
    if specialization:
        params["specialization"] = specialization
    r = _request("GET", f"{BASE_URL}/admin/doctors", params=params)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def admin_update_doctor(doctor_id: str, payload: dict) -> dict:
    """PUT /admin/doctors/{id} — update doctor settings."""
    r = _request("PUT", f"{BASE_URL}/admin/doctors/{doctor_id}", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def admin_get_config() -> list:
    """GET /admin/config — all scheduling config."""
    r = _request("GET", f"{BASE_URL}/admin/config")
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def admin_update_config(key: str, payload: dict) -> dict:
    """PUT /admin/config/{key} — update config value."""
    r = _request("PUT", f"{BASE_URL}/admin/config/{key}", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def admin_get_audit(action: str = "", from_date: str = "", to_date: str = "",
                    limit: int = 50, offset: int = 0) -> dict:
    """GET /admin/audit — query audit logs."""
    params = {"limit": limit, "offset": offset}
    if action:
        params["action"] = action
    if from_date:
        params["from_date"] = from_date
    if to_date:
        params["to_date"] = to_date
    r = _request("GET", f"{BASE_URL}/admin/audit", params=params)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def admin_list_patients(search: str = "", high_risk_only: bool = False,
                        specialization: str = "", doctor_id: str = "",
                        include_inactive: bool = False,
                        limit: int = 50, offset: int = 0) -> list:
    """GET /admin/patients — list patients."""
    params = {"limit": limit, "offset": offset}
    if search:
        params["search"] = search
    if high_risk_only:
        params["high_risk_only"] = "true"
    if include_inactive:
        params["include_inactive"] = "true"
    if specialization:
        params["specialization"] = specialization
    if doctor_id:
        params["doctor_id"] = doctor_id
    r = _request("GET", f"{BASE_URL}/admin/patients", params=params)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def admin_reset_risk(patient_id: str, new_score: float = 0.0) -> dict:
    """PUT /admin/patients/{id}/reset-risk — reset risk score."""
    r = _request(
        "PUT",
        f"{BASE_URL}/admin/patients/{patient_id}/reset-risk",
        json={"patient_id": patient_id, "new_score": new_score},
    )
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def admin_get_patient(patient_id: str) -> dict:
    """GET /admin/patients/{id} — full patient detail with appointments and relationships."""
    r = _request("GET", f"{BASE_URL}/admin/patients/{patient_id}")
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def admin_update_patient(patient_id: str, payload: dict) -> dict:
    """PUT /admin/patients/{id}/update — update patient profile."""
    r = _request(
        "PUT",
        f"{BASE_URL}/admin/patients/{patient_id}/update",
        json=payload,
    )
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def admin_list_sessions(date_str: str = "", status: str = "",
                        specialization: str = "", doctor_id: str = "") -> list:
    """GET /admin/sessions — all sessions."""
    params = {}
    if date_str:
        params["date_str"] = date_str
    if status:
        params["status"] = status
    if specialization:
        params["specialization"] = specialization
    if doctor_id:
        params["doctor_id"] = doctor_id
    r = _request("GET", f"{BASE_URL}/admin/sessions", params=params)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


# ─── Chat ──────────────────────────────────────────────────

def chat_health() -> dict:
    """GET /chat/health — Check if chatbot is configured."""
    r = _request("GET", f"{BASE_URL}/chat/health")
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def chat_send_message(message: str, patient_context: str = "") -> dict:
    """POST /chat/message — Send message. Server remembers conversation."""
    payload = {"message": message}
    if patient_context:
        payload["patient_context"] = patient_context
    r = _request(
        "POST",
        f"{BASE_URL}/chat/message",
        json=payload,
        timeout=60.0,
    )
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def chat_history() -> list:
    """GET /chat/history — Retrieve conversation history from server."""
    r = _request("GET", f"{BASE_URL}/chat/history")
    if r.status_code >= 400:
        return []
    data = r.json()
    return data.get("messages", [])


def chat_clear() -> dict:
    """POST /chat/clear — Clear conversation thread on server."""
    r = _request("POST", f"{BASE_URL}/chat/clear")
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def chat_transcribe(audio_bytes: bytes, filename: str = "audio.wav") -> dict:
    """POST /chat/transcribe — Send audio, get back transcribed text."""
    r = _request(
        "POST",
        f"{BASE_URL}/chat/transcribe",
        files={"audio": (filename, audio_bytes)},
        timeout=30.0,
    )
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def chat_tts(text: str, voice: str = "alloy") -> bytes:
    """POST /chat/tts — Send text, get back mp3 audio bytes."""
    r = _request(
        "POST",
        f"{BASE_URL}/chat/tts",
        json={"text": text, "voice": voice},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.content  # raw mp3 bytes


# ─── Ratings / Feedback ──────────────────────────────────────

def submit_rating(appointment_id: str, rating: int, review: str = "") -> dict:
    """POST /ratings — Submit a rating for a completed appointment."""
    payload = {"appointment_id": appointment_id, "rating": rating}
    if review:
        payload["review"] = review
    r = _request("POST", f"{BASE_URL}/ratings", json=payload)
    if r.status_code >= 400:
        _raise_api_error(r)
    return r.json()


def get_doctor_ratings(doctor_id: str) -> list:
    """GET /ratings/doctor/{id} — Get ratings for a doctor."""
    r = _request("GET", f"{BASE_URL}/ratings/doctor/{doctor_id}")
    if r.status_code >= 400:
        return []
    return r.json()


def get_doctor_rating_stats(doctor_id: str) -> dict:
    """GET /ratings/doctor/{id}/stats — Get avg rating stats."""
    r = _request("GET", f"{BASE_URL}/ratings/doctor/{doctor_id}/stats")
    if r.status_code >= 400:
        return {"avg_rating": 0, "total_ratings": 0}
    return r.json()
