"""DPMS v2 — Streamlit Frontend Router
======================================
Run:  streamlit run streamlit_app.py  (backend must be running on :8000)

Pages by role:
  Patient → Dashboard, Book Appointment, My Appointments, Profile
  Doctor  → Dashboard (date picker + queue), My Queue (today only), Session Controls
  Nurse   → Session & Queue (full patient management), Emergency Book
  Admin   → Session & Queue, Emergency Book, Cancel Session

Key patterns:
  - can_act_today = is_today AND sess_status == "active"  (guards queue-management buttons)
  - can_add_patient = (is_today OR is_future) AND sess_status == "active"  (guards Add Patient)
  - No auto-cancel/auto-complete. Doctor manually ends session when leaving.
    On "End Session": booked → no_show, checked_in → cancelled, in_progress blocks it.
  - st.session_state["dd_msg"] for persistent messages across Streamlit reruns
  - _db_get_all_sessions_for_doctor() = direct DB (temporary until API supports include_all)
"""
import streamlit as st
import sys, os

sys.path.insert(0, os.path.dirname(__file__))

st.set_page_config(page_title="DPMS v2", page_icon="🏥", layout="wide", initial_sidebar_state="expanded")

for key, default in {"access_token": None, "refresh_token": None, "user": None, "patient": None, "page": "login"}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# Import pages
from streamlit_pages.login import show_login, _handle_google_callback
from streamlit_pages.sidebar import show_sidebar
from streamlit_pages.patient import page_patient_dashboard, page_book_appointment, page_my_appointments, page_patient_profile
from streamlit_pages.doctor import page_doctor_dashboard, page_doctor_queue, page_doctor_session
from streamlit_pages.nurse import page_staff_session, page_nurse_emergency, page_nurse_patients
from streamlit_pages.admin import (page_admin_dashboard, page_admin_staff, page_admin_patients,
                                    page_admin_sessions, page_admin_audit)
from streamlit_pages.chatbot import page_chatbot


def page_dashboard():
    role = st.session_state.user["role"]
    if role == "patient":
        page_patient_dashboard()
    elif role == "doctor":
        page_doctor_dashboard()
    elif role == "admin":
        page_admin_dashboard()
    elif role == "nurse":
        page_admin_dashboard()


PAGE_MAP = {
    "login": show_login,
    "dashboard": page_dashboard,
    "book": page_book_appointment,
    "my_appointments": page_my_appointments,
    "profile": page_patient_profile,
    "doctor_queue": page_doctor_queue,
    "doctor_session": page_doctor_session,
    "staff_session": page_staff_session,
    "nurse_emergency": page_nurse_emergency,
    "nurse_patients": page_admin_patients,
    "nurse_sessions": page_admin_sessions,
    "admin_queue": page_staff_session,
    "admin_home": page_admin_dashboard,
    "admin_staff": page_admin_staff,
    "admin_patients": page_admin_patients,
    "admin_sessions_overview": page_admin_sessions,
    "admin_audit": page_admin_audit,
    "chatbot": page_chatbot,
}


def main():
    _handle_google_callback()
    if not st.session_state.access_token:
        show_login()
        return
    show_sidebar()
    page_fn = PAGE_MAP.get(st.session_state.get("page", "dashboard"), page_dashboard)
    try:
        page_fn()
    except Exception:
        # If _auto_logout cleared the session (token expired), rerun to show login
        if not st.session_state.access_token:
            st.rerun()
        raise  # Re-raise other errors normally


if __name__ == "__main__":
    main()
