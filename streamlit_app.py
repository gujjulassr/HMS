"""
DPMS v2 — Streamlit Frontend
==============================
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
from streamlit_pages import api_client as api

try:
    from audio_recorder_streamlit import audio_recorder
    HAS_AUDIO_RECORDER = True
except ImportError:
    HAS_AUDIO_RECORDER = False

st.set_page_config(page_title="DPMS v2", page_icon="🏥", layout="wide", initial_sidebar_state="expanded")

for key, default in {"access_token": None, "refresh_token": None, "user": None, "patient": None, "page": "login"}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════

def _fetch_all_doctors() -> list[dict]:
    """Cache doctors list."""
    try:
        return api.list_doctors()
    except Exception:
        return []


def _fetch_sessions_for_doctor(doctor_id: str, from_date: str = "", to_date: str = "") -> list[dict]:
    """Fetch sessions for a specific doctor with optional date range."""
    try:
        return api.get_doctor_sessions(doctor_id, from_date=from_date, to_date=to_date)
    except Exception:
        return []


def _db_get_sessions_by_doctor_id(doctor_id: str, date_str: str) -> list[dict]:
    """
    Direct DB query — fetches ALL sessions (any status) for a doctor on a date.
    If no sessions exist for that date, auto-creates morning + afternoon as 'inactive'.
    Uses doctor_id (not user_id) — for nurse/admin pickers.
    """
    import psycopg2
    import psycopg2.extras
    import uuid as _uuid_mod
    try:
        from config import get_settings as _get_settings
        _s = _get_settings()
        # Parse DB credentials from DATABASE_URL in config
        import re as _re
        _m = _re.search(r'://([^:]+):([^@]+)@([^:/]+):?(\d+)?/(.+)', _s.DATABASE_URL)
        conn = psycopg2.connect(
            host=_m.group(3) if _m else "localhost",
            port=int(_m.group(4)) if _m and _m.group(4) else 5432,
            dbname=_m.group(5) if _m else "dpms_v2",
            user=_m.group(1) if _m else "postgres",
            password=_m.group(2) if _m else "postgres",
        )
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Fetch existing sessions for this doctor on this date
        cur.execute("""
            SELECT s.id as session_id, s.doctor_id, s.session_date,
                   s.start_time, s.end_time, s.slot_duration_minutes,
                   s.max_patients_per_slot, s.total_slots, s.booked_count,
                   s.delay_minutes, s.status, s.notes
            FROM sessions s
            WHERE s.doctor_id = %s AND s.session_date = %s
            ORDER BY s.start_time
        """, (doctor_id, date_str))
        rows = cur.fetchall()

        existing_starts = set()
        for r in rows:
            existing_starts.add(str(r["start_time"])[:5])

        # Auto-create missing standard sessions as 'inactive'
        standard_sessions = [
            {"start": "09:00", "end": "13:00", "slots": 16, "dur": 15, "max_pp": 2},
            {"start": "14:00", "end": "17:00", "slots": 12, "dur": 15, "max_pp": 2},
        ]

        created = False
        for ss in standard_sessions:
            if ss["start"] not in existing_starts:
                new_id = str(_uuid_mod.uuid4())
                try:
                    cur.execute("""
                        INSERT INTO sessions (id, doctor_id, session_date, start_time, end_time,
                            slot_duration_minutes, max_patients_per_slot, scheduling_type,
                            total_slots, booked_count, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 'TIME_SLOT', %s, 0, 'inactive')
                    """, (new_id, doctor_id, date_str, ss["start"], ss["end"],
                          ss["dur"], ss["max_pp"], ss["slots"]))
                    created = True
                except Exception:
                    conn.rollback()

        if created:
            conn.commit()
            cur.execute("""
                SELECT s.id as session_id, s.doctor_id, s.session_date,
                       s.start_time, s.end_time, s.slot_duration_minutes,
                       s.max_patients_per_slot, s.total_slots, s.booked_count,
                       s.delay_minutes, s.status, s.notes
                FROM sessions s
                WHERE s.doctor_id = %s AND s.session_date = %s
                ORDER BY s.start_time
            """, (doctor_id, date_str))
            rows = cur.fetchall()

        cur.close()
        conn.close()
        results = []
        for r in rows:
            results.append({
                "session_id": str(r["session_id"]),
                "doctor_id": str(r["doctor_id"]),
                "session_date": str(r["session_date"]),
                "start_time": str(r["start_time"]),
                "end_time": str(r["end_time"]),
                "slot_duration_minutes": r["slot_duration_minutes"],
                "max_patients_per_slot": r["max_patients_per_slot"],
                "total_slots": r["total_slots"],
                "booked_count": r["booked_count"] or 0,
                "delay_minutes": int(r["delay_minutes"] or 0),
                "status": r["status"],
            })
        return results
    except Exception as e:
        # Fallback to API if DB connection fails
        try:
            return _fetch_sessions_for_doctor(doctor_id, from_date=date_str, to_date=date_str)
        except Exception:
            return []


def _db_get_all_sessions_for_doctor(user_id: str, date_str: str) -> list[dict]:
    """
    Direct DB query — fetches ALL sessions (any status) for a doctor on a date.
    If no sessions exist for that date, auto-creates the doctor's standard
    sessions (morning + afternoon) as 'inactive'. Doctor activates manually.
    """
    import psycopg2
    import psycopg2.extras
    import uuid as _uuid_mod
    try:
        from config import get_settings as _get_settings
        _s = _get_settings()
        # Parse DB credentials from DATABASE_URL in config
        import re as _re
        _m = _re.search(r'://([^:]+):([^@]+)@([^:/]+):?(\d+)?/(.+)', _s.DATABASE_URL)
        conn = psycopg2.connect(
            host=_m.group(3) if _m else "localhost",
            port=int(_m.group(4)) if _m and _m.group(4) else 5432,
            dbname=_m.group(5) if _m else "dpms_v2",
            user=_m.group(1) if _m else "postgres",
            password=_m.group(2) if _m else "postgres",
        )
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # First fetch existing sessions
        cur.execute("""
            SELECT s.id as session_id, s.doctor_id, s.session_date,
                   s.start_time, s.end_time, s.slot_duration_minutes,
                   s.max_patients_per_slot, s.total_slots, s.booked_count,
                   s.delay_minutes, s.status, s.notes
            FROM sessions s
            JOIN doctors d ON s.doctor_id = d.id
            WHERE d.user_id = %s AND s.session_date = %s
            ORDER BY s.start_time
        """, (user_id, date_str))
        rows = cur.fetchall()

        # Count how many sessions exist — if less than 2, fill in missing ones
        existing_starts = set()
        doctor_id = None
        for r in rows:
            existing_starts.add(str(r["start_time"])[:5])
            doctor_id = r["doctor_id"]

        # If we have no rows, look up doctor_id
        if not doctor_id:
            cur.execute("SELECT id FROM doctors WHERE user_id = %s", (user_id,))
            doc_row = cur.fetchone()
            doctor_id = doc_row["id"] if doc_row else None

        if doctor_id:
            # Standard sessions — only create the ones that don't exist yet
            # Always created as 'inactive'; doctor activates manually.
            standard_sessions = [
                {"start": "09:00", "end": "13:00", "slots": 16, "dur": 15, "max_pp": 2},
                {"start": "14:00", "end": "17:00", "slots": 12, "dur": 15, "max_pp": 2},
            ]

            created = False
            for ss in standard_sessions:
                if ss["start"] not in existing_starts:
                    new_id = str(_uuid_mod.uuid4())
                    try:
                        cur.execute("""
                            INSERT INTO sessions (id, doctor_id, session_date, start_time, end_time,
                                slot_duration_minutes, max_patients_per_slot, scheduling_type,
                                total_slots, booked_count, status)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, 'TIME_SLOT', %s, 0, 'inactive')
                        """, (new_id, str(doctor_id), date_str, ss["start"], ss["end"],
                              ss["dur"], ss["max_pp"], ss["slots"]))
                        created = True
                    except Exception as ins_err:
                        conn.rollback()
                        st.warning(f"Could not create {ss['start']} session: {ins_err}")

            if created:
                conn.commit()
                # Re-fetch all
                cur.execute("""
                    SELECT s.id as session_id, s.doctor_id, s.session_date,
                           s.start_time, s.end_time, s.slot_duration_minutes,
                           s.max_patients_per_slot, s.total_slots, s.booked_count,
                           s.delay_minutes, s.status, s.notes
                    FROM sessions s
                    WHERE s.doctor_id = %s AND s.session_date = %s
                    ORDER BY s.start_time
                """, (str(doctor_id), date_str))
                rows = cur.fetchall()

        cur.close()
        conn.close()
        results = []
        for r in rows:
            results.append({
                "session_id": str(r["session_id"]),
                "doctor_id": str(r["doctor_id"]),
                "session_date": str(r["session_date"]),
                "start_time": str(r["start_time"]),
                "end_time": str(r["end_time"]),
                "slot_duration_minutes": r["slot_duration_minutes"],
                "max_patients_per_slot": r["max_patients_per_slot"],
                "total_slots": r["total_slots"],
                "booked_count": r["booked_count"] or 0,
                "delay_minutes": int(r["delay_minutes"] or 0),
                "status": r["status"],
            })
        return results
    except Exception as e:
        st.error(f"DB error: {e}")
        return []



# NOTE: _db_get_all_sessions_for_doctor above is a temporary direct-DB fallback.
# Once FastAPI is restarted with include_all support, replace line in page_doctor_dashboard()
# that calls it with: api.get_doctor_sessions(doctor_id, from_date=str(picked), to_date=str(picked), include_all=True)


def _mark_noshow(appointment_id: str) -> bool:
    """Mark a single patient as no-show via API."""
    try:
        api.mark_single_noshow({"appointment_id": appointment_id})
        return True
    except Exception as e:
        st.error(f"No-show error: {e}")
        return False


def _calc_and_update_delay(sid: str, s_start: str, dur: int, completed_slot: int):
    """
    After completing a patient, calculate if doctor is running late or caught up.
    Compare current time vs when the completed slot was supposed to end.
    Auto-update session delay.
    """
    from datetime import datetime as _dt
    try:
        sh, sm = int(s_start[:2]), int(s_start[3:5])
        # The completed slot was supposed to end at:
        slot_end_min = sh * 60 + sm + completed_slot * dur
        now = _dt.now()
        now_min = now.hour * 60 + now.minute

        # Delay = how many minutes behind schedule
        delay = max(0, now_min - slot_end_min)

        api.update_delay({
            "session_id": sid,
            "delay_minutes": delay,
            "reason": f"Auto-calculated after completing slot #{completed_slot}",
        })
        return delay
    except Exception:
        return None


def _smart_session_picker(key: str) -> str | None:
    """
    Smart picker: Department → Doctor → Date → Session.
    Strict selection — nurse must pick each step explicitly.
    """
    if "all_doctors" not in st.session_state:
        st.session_state.all_doctors = _fetch_all_doctors()
    doctors = st.session_state.all_doctors

    if not doctors:
        st.warning("No doctors found.")
        if st.button("🔄 Reload doctors", key=f"reload_doc_{key}"):
            st.session_state.all_doctors = _fetch_all_doctors()
            st.rerun()
        return None

    # Step 1: Department — must pick one (no "All")
    specializations = sorted(set(d["specialization"] for d in doctors))
    spec_options = ["— Select Department —"] + specializations
    chosen_spec = st.selectbox("🏥 Department", spec_options, key=f"spec_{key}")

    if chosen_spec == "— Select Department —":
        st.info("👆 Please select a department to continue.")
        return None

    filtered_docs = [d for d in doctors if d["specialization"] == chosen_spec]

    # Step 2: Doctor — must pick one (no auto-select)
    doc_labels = ["— Select Doctor —"] + [
        d['full_name'] if d['full_name'].lower().startswith("dr") else f"Dr. {d['full_name']}"
        for d in filtered_docs
    ]
    if len(filtered_docs) == 0:
        st.info("No doctors in this department.")
        return None
    doc_choice = st.selectbox("🩺 Doctor", doc_labels, key=f"doc_{key}")

    if doc_choice == "— Select Doctor —":
        st.info("👆 Please select a doctor to continue.")
        return None

    chosen_doc = filtered_docs[doc_labels.index(doc_choice) - 1]  # -1 for placeholder

    # Step 3: Date filter
    from datetime import date, timedelta
    today = date.today()
    date_pick = st.date_input("📅 Date", value=today, key=f"date_{key}")
    from_d, to_d = date_pick, date_pick

    # For single-day picks (Today/Tomorrow), use DB function that auto-creates sessions
    if from_d and from_d == to_d:
        sessions = _db_get_sessions_by_doctor_id(
            str(chosen_doc["doctor_id"]), str(from_d)
        )
    else:
        # Multi-day range — use API
        sessions = _fetch_sessions_for_doctor(
            chosen_doc["doctor_id"],
            from_date=str(from_d) if from_d else "",
            to_date=str(to_d) if to_d else "",
        )

    # Show all sessions (active, inactive, completed) — not just active
    usable_sessions = [s for s in sessions if s["status"] in ("active", "inactive", "completed")]

    if not usable_sessions:
        st.info(f"No sessions found for {chosen_doc['full_name']} on {date_pick}.")
        return None

    # Step 4: Session (time) picker — show status in label
    def _sess_label(s):
        status_tag = ""
        if s["status"] == "inactive":
            status_tag = " ⚪ INACTIVE"
        elif s["status"] == "completed":
            status_tag = " ✔️ COMPLETED"
        return (f"{s['session_date']}  •  {s['start_time'][:5]} – {s['end_time'][:5]}  •  "
                f"{s['booked_count']}/{s['total_slots']} booked{status_tag}")

    sess_labels = [_sess_label(s) for s in usable_sessions]
    if len(usable_sessions) == 1:
        chosen_sess = usable_sessions[0]
    else:
        sess_idx = st.selectbox("🕐 Session", range(len(sess_labels)),
                                format_func=lambda i: sess_labels[i], key=f"sess_{key}")
        chosen_sess = usable_sessions[sess_idx]

    # If session is inactive, show activate button
    if chosen_sess["status"] == "inactive":
        st.warning(f"⚪ This session is **inactive**. Activate it to manage patients.")
        if st.button("🟢 Activate Session", type="primary", use_container_width=True, key=f"activate_{key}"):
            try:
                r = api.activate_session({"session_id": chosen_sess["session_id"]})
                st.success(r.get("message", "Session activated!"))
                # Clear cached sessions so it reloads
                st.session_state.pop("today_sessions", None)
                import time as _t; _t.sleep(0.5)
                st.rerun()
            except Exception as e:
                st.error(f"Failed to activate: {e}")
        return None  # Don't load queue until activated

    # Show session info
    if len(usable_sessions) == 1:
        st.caption(f"📍 Session: **{sess_labels[0]}**")

    return chosen_sess["session_id"]


def _time_to_minutes_safe(q: dict) -> int:
    """Extract session start time in minutes from queue response. Fallback to 0."""
    # The queue entries have original_slot_time; first entry's slot gives us the base
    for entry in q.get("queue", []):
        t = entry.get("original_slot_time")
        if t:
            # Could be "HH:MM:SS" string or "HH:MM"
            parts = str(t).split(":")
            return int(parts[0]) * 60 + int(parts[1])
    return 9 * 60  # default 9:00 AM


def _status_badge(status: str) -> str:
    return {"booked": "📅 Booked", "checked_in": "✅ Waiting", "in_progress": "🔄 With Doctor",
            "completed": "✔️ Done", "cancelled": "❌ Cancelled", "no_show": "⚠️ No-show"}.get(status, status)


# ════════════════════════════════════════════════════════════
# AUTH
# ════════════════════════════════════════════════════════════

def show_login():
    st.title("🏥 DPMS v2")
    st.caption("Doctor-Patient Management System")

    # Show Google login error if redirected back
    google_err = st.session_state.pop("_google_error", None)
    if google_err:
        st.error(google_err)

    tab_login, tab_register = st.tabs(["Login", "Register"])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login", use_container_width=True)
        if submitted and email and password:
            try:
                tokens = api.login(email, password)
                st.session_state.access_token = tokens["access_token"]
                st.session_state.refresh_token = tokens["refresh_token"]
                me = api.get_me()
                st.session_state.user = me["user"]
                st.session_state.patient = me.get("patient")
                st.session_state.page = "dashboard"
                st.rerun()
            except Exception as e:
                st.error(f"Login failed: {e}")
        st.divider()
        # Google OAuth login
        st.markdown(
            '<a href="http://127.0.0.1:8000/api/auth/google/login" target="_self" '
            'style="display:inline-flex;align-items:center;gap:8px;padding:10px 24px;'
            'background:#fff;border:1px solid #dadce0;border-radius:8px;color:#3c4043;'
            'font-size:14px;font-weight:500;text-decoration:none;cursor:pointer;'
            'width:100%;justify-content:center;box-sizing:border-box;">'
            '<svg width="18" height="18" viewBox="0 0 48 48"><path fill="#EA4335" '
            'd="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 '
            '14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>'
            '<path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94'
            'c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>'
            '<path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14'
            '.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>'
            '<path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 '
            '1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 '
            '14.62 48 24 48z"/></svg>'
            'Sign in with Google</a>',
            unsafe_allow_html=True,
        )
        st.divider()
        st.caption("Test accounts — password: `password123`")
        st.code("ravi.kumar@gmail.com      (patient)\npriya.sharma@gmail.com    (patient)\ndr.ananya@hospital.com    (doctor)\nnurse.lakshmi@hospital.com (nurse)\nadmin@hospital.com        (admin)", language=None)

    with tab_register:
        with st.form("register_form"):
            full_name = st.text_input("Full Name")
            reg_email = st.text_input("Email", key="reg_email")
            reg_password = st.text_input("Password", type="password", key="reg_pass")
            c1, c2 = st.columns(2)
            with c1:
                from datetime import date as _reg_d
                dob = st.date_input("Date of Birth", value=_reg_d(1990, 1, 1),
                                     min_value=_reg_d(1920, 1, 1), max_value=_reg_d.today())
            with c2:
                gender = st.selectbox("Gender", ["male", "female", "other"])
            phone = st.text_input("Phone (optional)", key="reg_phone")
            reg_submit = st.form_submit_button("Register", use_container_width=True)
        if reg_submit and full_name and reg_email and reg_password:
            try:
                payload = {"email": reg_email, "password": reg_password, "full_name": full_name,
                           "date_of_birth": str(dob), "gender": gender}
                if phone:
                    payload["phone"] = phone
                tokens = api.register(payload)
                st.session_state.access_token = tokens["access_token"]
                st.session_state.refresh_token = tokens["refresh_token"]
                me = api.get_me()
                st.session_state.user = me["user"]
                st.session_state.patient = me.get("patient")
                st.session_state.page = "dashboard"
                st.rerun()
            except Exception as e:
                st.error(f"Registration failed: {e}")


# ════════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════════

def show_sidebar():
    user = st.session_state.user
    role = user["role"]
    with st.sidebar:
        st.markdown(f"### 👤 {user['full_name']}")
        st.caption(f"Role: **{role.upper()}**")
        st.divider()

        menus = {
            "patient": {"dashboard": "🏠 Dashboard", "book": "📅 Book Appointment",
                        "my_appointments": "📋 My Appointments", "profile": "👤 My Profile",
                        "chatbot": "🤖 AI Assistant"},
            "doctor": {"dashboard": "🏠 Dashboard", "doctor_queue": "📋 My Queue",
                       "doctor_session": "⚙️ Session Controls",
                       "chatbot": "🤖 AI Assistant"},
            "nurse": {"dashboard": "🏠 Dashboard", "staff_session": "📋 Session & Queue",
                      "nurse_patients": "🏥 Patient Lookup",
                      "nurse_emergency": "🚨 Emergency Book",
                      "chatbot": "🤖 AI Assistant"},
            "admin": {
                "admin_home": "🏠 Dashboard",
                "admin_users": "👥 Users",
                "admin_doctors": "🩺 Doctors",
                "admin_sessions_overview": "📅 Sessions",
                "admin_patients": "🏥 Patients",
                "admin_config": "⚙️ Config",
                "admin_audit": "📜 Audit Logs",
                "staff_session": "📋 Session & Queue",
                "nurse_emergency": "🚨 Emergency Book",
                "admin_cancel": "❌ Cancel Session",
                "chatbot": "🤖 AI Assistant",
            },
        }
        for key, label in menus.get(role, {"dashboard": "🏠 Dashboard"}).items():
            if st.button(label, key=f"nav_{key}", use_container_width=True):
                st.session_state.page = key
                st.rerun()
        st.divider()
        if st.button("🚪 Logout", use_container_width=True):
            for k in ["access_token", "refresh_token", "user", "patient", "today_sessions"]:
                st.session_state[k] = None
            st.session_state.page = "login"
            st.rerun()


# ════════════════════════════════════════════════════════════
# PATIENT PAGES
# ════════════════════════════════════════════════════════════

def page_patient_dashboard():
    tc1, tc2 = st.columns([6, 1])
    tc1.title("🏠 Dashboard")
    if tc2.button("🔄 Refresh", key="refresh_patient_dash", use_container_width=True):
        st.rerun()
    user = st.session_state.user
    patient = st.session_state.patient

    # ── Load full profile for richer info ──
    full_profile = None
    try:
        full_profile = api.get_my_profile()
    except Exception:
        pass

    # ── Patient info card ──
    with st.container(border=True):
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Name", user["full_name"])
        c2.metric("Gender", (patient.get("gender") or "—").title() if patient else "—")
        c3.metric("Blood Group", patient.get("blood_group") or "—" if patient else "—")
        age_val = full_profile.get("age", "—") if full_profile else "—"
        c4.metric("Age", age_val)
        risk = patient.get("risk_score", 0) if patient else 0
        risk_label = "Low" if risk < 20 else ("Medium" if risk < 50 else "High")
        c5.metric("Risk Score", f"{risk} ({risk_label})")

    # ── Quick info row ──
    info_parts = []
    phone = (full_profile or {}).get("phone") or user.get("phone")
    if phone:
        info_parts.append(f"📞 {phone}")
    abha = (patient or {}).get("abha_id")
    if abha:
        info_parts.append(f"🆔 ABHA: {abha}")
    if full_profile and full_profile.get("emergency_contact_name"):
        info_parts.append(f"🚨 Emergency: {full_profile.get('emergency_contact_name', '')}")
    if info_parts:
        st.caption("  |  ".join(info_parts))

    # Warn if profile is incomplete
    if full_profile:
        missing = []
        if not full_profile.get("abha_id"):
            missing.append("UHID (ABHA ID)")
        if not full_profile.get("phone"):
            missing.append("phone")
        if not full_profile.get("blood_group"):
            missing.append("blood group")
        if not full_profile.get("emergency_contact_name"):
            missing.append("emergency contact")
        if missing:
            st.warning(f"⚠️ Your profile is incomplete — please add: {', '.join(missing)}. Go to 👤 My Profile to update.")

    # ── Quick actions ──
    st.divider()
    qa1, qa2, qa3 = st.columns(3)
    with qa1:
        if st.button("📅 Book New Appointment", use_container_width=True, type="primary"):
            st.session_state.page = "book"
            st.rerun()
    with qa2:
        if st.button("📋 View All Appointments", use_container_width=True):
            st.session_state.page = "my_appointments"
            st.rerun()
    with qa3:
        if st.button("🤖 Chat with AI Assistant", use_container_width=True):
            st.session_state.page = "chatbot"
            st.rerun()

    # ── Upcoming / Active appointments ──
    st.divider()
    st.subheader("Upcoming Appointments")
    try:
        appts = api.get_my_appointments().get("appointments", [])
        active = [a for a in appts if a.get("status") in ("booked", "checked_in", "in_progress")]
        if not active:
            st.info("No upcoming appointments. Use '📅 Book Appointment' to schedule one!")
        for a in active:
            with st.container(border=True):
                row1c1, row1c2, row1c3 = st.columns([3, 3, 1])
                row1c1.write(f"**🩺 {a.get('doctor_name', 'Doctor')}** — {a.get('specialization', '')}")
                appt_date = a.get("session_date", "")
                appt_time = a.get("start_time", "")
                if appt_time:
                    appt_time = str(appt_time)[:5]
                row1c2.write(f"📅 {appt_date}  •  🕐 {appt_time}  •  Slot {a.get('slot_number', '?')}")
                row1c3.write(_status_badge(a.get("status", "unknown")))
                if a.get("delay_minutes", 0) > 0:
                    st.warning(f"⏱️ Doctor running ~{a['delay_minutes']} min late. Expected wait adjusted accordingly.")
                if a.get("notes"):
                    st.caption(f"📝 {a['notes']}")

        # Show recent completed
        completed = [a for a in appts if a["status"] == "completed"][:3]
        if completed:
            st.divider()
            st.subheader("Recent Visits")
            for a in completed:
                with st.container(border=True):
                    rc1, rc2, rc3 = st.columns([3, 3, 1])
                    rc1.write(f"**{a.get('doctor_name', 'Doctor')}** — {a.get('specialization', '')}")
                    rc2.write(f"📅 {a.get('session_date', '')}")
                    rc3.write("✅ Completed")
                    if a.get("notes"):
                        st.caption(f"📝 {a['notes']}")
    except Exception as e:
        st.error(f"Could not load appointments: {e}")


def _calc_slot_time(start_time_str: str, slot_duration: int, slot_num: int) -> str:
    """Calculate the actual time for a given slot number."""
    try:
        parts = str(start_time_str).split(":")
        start_h, start_m = int(parts[0]), int(parts[1])
        total_minutes = start_h * 60 + start_m + (slot_num - 1) * slot_duration
        h, m = divmod(total_minutes, 60)
        return f"{h:02d}:{m:02d}"
    except Exception:
        return f"Slot {slot_num}"


def page_book_appointment():
    tc1, tc2 = st.columns([6, 1])
    tc1.title("📅 Book an Appointment")
    if tc2.button("🔄 Refresh", key="refresh_book", use_container_width=True):
        st.rerun()

    # ── Step 1: Department & Doctor selection ──
    st.subheader("Step 1 — Choose Department & Doctor")

    # Fetch departments for browsing
    try:
        departments = api.list_departments()
        if isinstance(departments, list) and departments:
            if isinstance(departments[0], dict):
                dept_list = [d.get("specialization", d.get("name", "")) for d in departments]
            else:
                dept_list = departments
        else:
            dept_list = []
    except Exception:
        dept_list = []

    dc1, dc2 = st.columns([1, 2])
    with dc1:
        dept_options = ["All Departments"] + dept_list
        selected_dept = st.selectbox("Department", dept_options, key="book_dept")
        spec_filter = "" if selected_dept == "All Departments" else selected_dept

    try:
        doctors = api.list_doctors(spec_filter)
    except Exception as e:
        st.error(f"Could not load doctors: {e}"); return
    if not doctors:
        st.info("No doctors found for this department."); return

    with dc2:
        doc_labels = [
            f"🩺 {d['full_name']}  •  {d['specialization']}  •  ⭐ {d.get('avg_rating', '—')}  •  ₹{d.get('consultation_fee', '—')}"
            for d in doctors
        ]
        doc_idx = st.selectbox("Select Doctor", range(len(doc_labels)), format_func=lambda i: doc_labels[i])
    selected_doc = doctors[doc_idx]

    # Show doctor info card
    with st.container(border=True):
        di1, di2, di3, di4 = st.columns(4)
        di1.write(f"**Doctor:** {selected_doc['full_name']}")
        di2.write(f"**Specialization:** {selected_doc['specialization']}")
        di3.write(f"**Fee:** ₹{selected_doc.get('consultation_fee', '—')}")
        di4.write(f"**Rating:** ⭐ {selected_doc.get('avg_rating', '—')}")

    # ── Step 2: Pick session ──
    st.divider()
    st.subheader(f"Step 2 — Pick a Session")
    try:
        sessions = api.get_doctor_sessions(selected_doc["doctor_id"])
        active_sessions = [s for s in sessions if s["status"] == "active"]
    except Exception as e:
        st.error(f"Could not load sessions: {e}"); return
    if not active_sessions:
        st.info(f"No available sessions for {selected_doc['full_name']}. Try another doctor."); return

    sess_labels = []
    for s in active_sessions:
        start = str(s.get("start_time", ""))[:5]
        end = str(s.get("end_time", ""))[:5]
        avail = s.get("available_capacity", s.get("total_slots", 0) - s.get("booked_count", 0))
        sess_labels.append(f"📅 {s['session_date']}  •  🕐 {start}–{end}  •  {avail} slots free")
    sess_idx = st.selectbox("Select session", range(len(sess_labels)), format_func=lambda i: sess_labels[i])
    selected_sess = active_sessions[sess_idx]

    # ── Step 3: Slot selection with time display ──
    st.divider()
    st.subheader("Step 3 — Choose Time Slot")

    total_slots = selected_sess.get("total_slots", 1)
    slot_duration = selected_sess.get("slot_duration_minutes", 15)
    start_time = str(selected_sess.get("start_time", "09:00"))

    # Build slot options with times — filter out past slots for today
    from datetime import date as _pb_d, datetime as _pb_dt
    _pb_is_today = str(selected_sess.get("session_date", "")) == str(_pb_d.today())
    _pb_now_min = _pb_dt.now().hour * 60 + _pb_dt.now().minute
    slot_options = []  # list of (slot_number, label)
    for i in range(1, total_slots + 1):
        slot_time = _calc_slot_time(start_time, slot_duration, i)
        if _pb_is_today:
            try:
                hh, mm = int(start_time[:2]), int(start_time[3:5])
                t_min = hh * 60 + mm + (i - 1) * slot_duration
                if t_min + slot_duration <= _pb_now_min:
                    continue  # slot already passed
            except Exception:
                pass
        slot_options.append((i, f"Slot {i} — {slot_time}"))

    if not slot_options:
        st.warning("All time slots for this session have already passed. Please pick a different session.")
        return
    selected_slot_idx = st.selectbox("Pick a time slot", range(len(slot_options)),
                                      format_func=lambda idx: slot_options[idx][1])
    slot_num = slot_options[selected_slot_idx][0]

    # ── Step 4: Who is this appointment for? ──
    st.divider()
    st.subheader("Step 4 — Who is this appointment for?")

    # Load existing family members
    try:
        rels = api.get_my_relationships()
        approved = [r for r in rels if r["is_approved"]]
    except Exception:
        approved = []

    self_id = st.session_state.patient["id"] if st.session_state.patient else ""

    # Build booking-for options
    booking_options = ["Myself"]
    family_map = {}  # index -> beneficiary_patient_id
    for r in approved:
        if r["relationship_type"] == "self":
            continue
        label = f"{r.get('beneficiary_name', '?')} ({r['relationship_type'].title()})"
        booking_options.append(label)
        family_map[len(booking_options) - 1] = r["beneficiary_patient_id"]

    booking_choice = st.radio("Booking for", booking_options, horizontal=True, key="book_for_radio")
    booking_idx = booking_options.index(booking_choice)

    my_name = st.session_state.user.get("full_name", "Me") if st.session_state.user else "Me"

    if booking_idx == 0:
        # Booking for self
        beneficiary_id = self_id
        selected_beneficiary_name = my_name
    elif booking_idx in family_map:
        # Booking for existing family member
        beneficiary_id = family_map[booking_idx]
        selected_beneficiary_name = booking_choice.split(" (")[0]
        st.caption(f"Booking on behalf of **{selected_beneficiary_name}**")
    else:
        beneficiary_id = self_id
        selected_beneficiary_name = my_name

    # ── Step 5: Symptoms ──
    st.divider()
    st.subheader("Step 5 — Reason for Visit")
    symptoms = st.text_area("Symptoms / Reason for Visit *",
                             placeholder="Describe your symptoms or reason for visiting (e.g., persistent headache for 3 days, fever, chest pain...)",
                             height=80)
    if not symptoms:
        st.caption("⚠️ Please describe your symptoms — this helps the doctor prepare for your visit.")

    # ── Booking summary & confirm ──
    st.divider()
    slot_time_str = _calc_slot_time(start_time, slot_duration, slot_num)
    with st.container(border=True):
        st.markdown("**📋 Booking Summary**")
        sc1, sc2 = st.columns(2)
        sc1.write(f"**Patient:** {selected_beneficiary_name}")
        sc1.write(f"**Doctor:** {selected_doc['full_name']} ({selected_doc['specialization']})")
        sc2.write(f"**Date:** {selected_sess['session_date']}  •  **Time:** {slot_time_str}")
        sc2.write(f"**Fee:** ₹{selected_doc.get('consultation_fee', '—')}")
        if symptoms:
            st.caption(f"**Symptoms:** {symptoms[:100]}{'...' if len(symptoms) > 100 else ''}")

    if st.button("✅ Confirm Booking", type="primary", use_container_width=True,
                  disabled=not symptoms.strip()):
        try:
            result = api.book_appointment({
                "session_id": selected_sess["session_id"],
                "slot_number": slot_num,
                "beneficiary_patient_id": beneficiary_id,
            })
            if result["status"] == "booked":
                st.success(f"✅ {result['message']}")
                st.balloons()
            else:
                st.warning(f"⏳ {result['message']}")
        except Exception as e:
            st.error(f"Booking failed: {e}")


def page_my_appointments():
    tc1, tc2 = st.columns([6, 1])
    tc1.title("📋 My Appointments")
    if tc2.button("🔄 Refresh", key="refresh_my_appts", use_container_width=True):
        st.rerun()

    try:
        appts = api.get_my_appointments().get("appointments", [])
    except Exception as e:
        st.error(f"Could not load: {e}"); return
    if not appts:
        st.info("No appointments yet. Book your first appointment from the sidebar!")
        return

    # Summary counts
    active_list = [a for a in appts if a.get("status") in ("booked", "checked_in", "in_progress")]
    completed_list = [a for a in appts if a.get("status") == "completed"]
    cancelled_list = [a for a in appts if a.get("status") in ("cancelled", "no_show")]
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Total", len(appts))
    mc2.metric("Active", len(active_list))
    mc3.metric("Completed", len(completed_list))
    mc4.metric("Cancelled", len(cancelled_list))

    st.divider()

    for group_name, statuses in [("🟢 Active Appointments", ["in_progress", "checked_in", "booked"]),
                                  ("✅ Completed Visits", ["completed"]),
                                  ("❌ Cancelled / No-Show", ["cancelled", "no_show"])]:
        group = [a for a in appts if a.get("status") in statuses]
        if not group:
            continue
        st.subheader(group_name)
        for a in group:
            with st.container(border=True):
                c1, c2, c3 = st.columns([3, 3, 1])
                c1.write(f"**🩺 {a.get('doctor_name', 'Doctor')}** — {a.get('specialization', '')}")
                appt_time = a.get("slot_time") or str(a.get("start_time", ""))[:5]
                c2.write(f"📅 {a.get('session_date', '')}  •  🕐 {appt_time}  •  Slot {a.get('slot_number', '?')}")
                c3.write(_status_badge(a.get("status", "unknown")))
                # Additional info row
                info_bits = []
                if a.get("priority_tier"):
                    info_bits.append(f"Priority: {a['priority_tier']}")
                if a.get("is_emergency"):
                    info_bits.append("🚨 Emergency")
                if a.get("delay_minutes", 0) > 0:
                    info_bits.append(f"⏱️ Delay: ~{a['delay_minutes']} min")
                if info_bits:
                    st.caption("  |  ".join(info_bits))
                if a.get("notes"):
                    st.caption(f"📝 Notes: {a['notes']}")

                # Actions
                appt_date_str = a.get("session_date", "")
                try:
                    from datetime import date as _pd
                    appt_is_past = _pd.fromisoformat(str(appt_date_str)) < _pd.today() if appt_date_str else False
                except Exception:
                    appt_is_past = False

                _appt_status = a.get("status", "")
                _appt_id = a.get("appointment_id", "")
                if _appt_status in ("booked", "checked_in") and not appt_is_past:
                    if st.button("❌ Cancel Appointment", key=f"cancel_{_appt_id}",
                                  help="Warning: cancelling affects your risk score"):
                        try:
                            r = api.cancel_appointment({"appointment_id": _appt_id, "reason": "Cancelled via dashboard"})
                            st.warning(f"Cancelled. Risk penalty: +{r.get('risk_delta', 0)}  •  New score: {r.get('new_risk_score', '?')}")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed: {e}")
                elif _appt_status in ("booked", "checked_in") and appt_is_past:
                    st.caption("⏰ Past appointment — cannot cancel.")

                if _appt_status == "cancelled" and not appt_is_past:
                    if st.button("↩ Undo Cancel — Rebook", key=f"undo_cancel_{_appt_id}",
                                  help="Changed your mind? Restore this appointment and reverse risk penalty."):
                        try:
                            r = api.undo_cancel({"appointment_id": _appt_id, "reason": "Patient undid cancellation"})
                            st.success(f"↩ Appointment restored! Risk reversed by {r.get('risk_reversed', 0)} points.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed: {e}")
                elif _appt_status == "cancelled" and appt_is_past:
                    st.caption("⏰ Past appointment — cannot rebook.")

                # ── Rating form for completed appointments ──
                if _appt_status == "completed":
                    _rating_key = f"rating_{_appt_id}"
                    # Check if already in "show form" state
                    if st.session_state.get(f"show_rate_{_appt_id}"):
                        st.markdown("---")
                        st.markdown("**⭐ Rate this visit**")
                        _stars = st.slider("Rating", 1, 5, 4, key=f"stars_{_appt_id}")
                        _review = st.text_area("Review (optional)", key=f"review_{_appt_id}",
                                               placeholder="How was your experience?", max_chars=2000)
                        rc1, rc2 = st.columns(2)
                        if rc1.button("Submit Rating", key=f"submit_rate_{_appt_id}", type="primary"):
                            try:
                                api.submit_rating(_appt_id, _stars, _review)
                                st.session_state[f"rated_{_appt_id}"] = True
                                st.session_state.pop(f"show_rate_{_appt_id}", None)
                                st.success("Thank you for your feedback!")
                                st.rerun()
                            except Exception as e:
                                err_msg = str(e)
                                if "already been rated" in err_msg:
                                    st.info("You've already rated this appointment.")
                                    st.session_state[f"rated_{_appt_id}"] = True
                                else:
                                    st.error(f"Could not submit rating: {e}")
                        if rc2.button("Cancel", key=f"cancel_rate_{_appt_id}"):
                            st.session_state.pop(f"show_rate_{_appt_id}", None)
                            st.rerun()
                    elif not st.session_state.get(f"rated_{_appt_id}"):
                        if st.button("⭐ Rate this visit", key=f"rate_btn_{_appt_id}"):
                            st.session_state[f"show_rate_{_appt_id}"] = True
                            st.rerun()


def page_patient_profile():
    tc1, tc2 = st.columns([6, 1])
    tc1.title("👤 My Profile")
    if tc2.button("🔄 Refresh", key="refresh_profile", use_container_width=True):
        st.rerun()
    try:
        p = api.get_my_profile()
    except Exception as e:
        st.error(f"Could not load: {e}"); return

    # ── Personal details card ──
    with st.container(border=True):
        st.markdown("**Personal Information**")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.write(f"**Name:** {p['full_name']}")
            st.write(f"**Email:** {p['email']}")
            st.write(f"**Phone:** {p.get('phone') or '⚠️ Not set'}")
        with c2:
            st.write(f"**Date of Birth:** {p['date_of_birth']}")
            st.write(f"**Age:** {p['age']} years")
            st.write(f"**Gender:** {p.get('gender', '—').title()}")
        with c3:
            st.write(f"**Blood Group:** {p.get('blood_group') or '⚠️ Not set'}")
            st.write(f"**ABHA ID:** {p.get('abha_id') or '—'}")
            risk = p.get('risk_score', 0)
            risk_color = "🟢" if risk < 20 else ("🟡" if risk < 50 else "🔴")
            st.write(f"**Risk Score:** {risk_color} {risk}")

    # ── Emergency contact card ──
    with st.container(border=True):
        st.markdown("**Emergency Contact**")
        ec1, ec2, ec3 = st.columns(3)
        ec1.write(f"**Name:** {p.get('emergency_contact_name') or '⚠️ Not set'}")
        ec2.write(f"**Phone:** {p.get('emergency_contact_phone') or '⚠️ Not set'}")
        ec3.write(f"**Address:** {p.get('address') or '⚠️ Not set'}")

    # ── Check for missing required fields ──
    missing = []
    if not p.get("phone"):
        missing.append("Phone number")
    if not p.get("blood_group"):
        missing.append("Blood group")
    if not p.get("emergency_contact_name"):
        missing.append("Emergency contact name")
    if not p.get("emergency_contact_phone"):
        missing.append("Emergency contact phone")
    if missing:
        st.warning(f"⚠️ Please complete your profile — missing: {', '.join(missing)}")

    # ── Update form ──
    st.divider()
    st.subheader("Update Profile")
    with st.form("update_profile"):
        uc1, uc2 = st.columns(2)
        with uc1:
            new_phone = st.text_input("Phone Number", value=p.get("phone") or "",
                                       placeholder="e.g. 9876543210")
            new_blood = st.selectbox("Blood Group",
                                      options=["", "A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"],
                                      index=["", "A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"].index(p.get("blood_group") or ""))
            new_abha = st.text_input("ABHA ID", value=p.get("abha_id") or "",
                                      placeholder="14-digit ABHA number")
        with uc2:
            new_emergency_name = st.text_input("Emergency Contact Name",
                                                value=p.get("emergency_contact_name") or "",
                                                placeholder="e.g. Rahul Kumar")
            new_emergency_phone = st.text_input("Emergency Contact Phone",
                                                 value=p.get("emergency_contact_phone") or "",
                                                 placeholder="e.g. 9876543210")
            new_addr = st.text_input("Address", value=p.get("address") or "",
                                      placeholder="e.g. 123 MG Road, Bangalore")

        if st.form_submit_button("💾 Save Changes", use_container_width=True, type="primary"):
            payload = {}
            if new_phone: payload["phone"] = new_phone
            if new_blood: payload["blood_group"] = new_blood
            if new_abha: payload["abha_id"] = new_abha
            if new_emergency_name: payload["emergency_contact_name"] = new_emergency_name
            if new_emergency_phone: payload["emergency_contact_phone"] = new_emergency_phone
            if new_addr: payload["address"] = new_addr
            if payload:
                try:
                    api.update_my_profile(payload)
                    st.success("✅ Profile updated!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed: {e}")
            else:
                st.info("No changes to save.")

    # ── Family Members / Beneficiaries ──
    st.divider()
    st.subheader("👨‍👩‍👧‍👦 Family Members (Book for Others)")
    st.caption("Add family members here so you can book appointments on their behalf.")

    # Show existing relationships
    try:
        rels = api.get_my_relationships()
        approved = [r for r in rels if r["is_approved"]]
        pending = [r for r in rels if not r["is_approved"]]
    except Exception:
        rels, approved, pending = [], [], []

    family_count = 0

    def _show_family_card(r, status_icon, status_label, idx):
        """Render a single family member card with full details and edit option."""
        rel_id = r.get("relationship_id", "")
        edit_key = f"edit_fam_{rel_id}"

        with st.container(border=True):
            # Header row: name, relationship, status, edit button
            fc1, fc2, fc3, fc4 = st.columns([3, 2, 1, 1])
            fc1.write(f"**{r.get('beneficiary_name', 'Unknown')}**")
            fc2.write(f"Relation: {r['relationship_type'].title()}")
            fc3.write(f"{status_icon} {status_label}")
            if fc4.button("✏️ Edit", key=f"btn_edit_{idx}"):
                st.session_state[edit_key] = not st.session_state.get(edit_key, False)
                st.rerun()

            # Detail rows — show whatever is available
            details = []
            if r.get("beneficiary_gender"):
                details.append(f"**Gender:** {r['beneficiary_gender'].title()}")
            if r.get("beneficiary_age") is not None:
                details.append(f"**Age:** {r['beneficiary_age']}")
            if r.get("beneficiary_blood_group"):
                details.append(f"**Blood Group:** {r['beneficiary_blood_group']}")
            if r.get("beneficiary_phone"):
                details.append(f"**Phone:** {r['beneficiary_phone']}")
            if r.get("beneficiary_abha_id"):
                details.append(f"**UHID:** {r['beneficiary_abha_id']}")
            if r.get("beneficiary_address"):
                details.append(f"**Address:** {r['beneficiary_address']}")
            if r.get("beneficiary_emergency_contact_name"):
                ec = r['beneficiary_emergency_contact_name']
                if r.get("beneficiary_emergency_contact_phone"):
                    ec += f" ({r['beneficiary_emergency_contact_phone']})"
                details.append(f"**Emergency Contact:** {ec}")

            if details:
                st.caption(" · ".join(details))

            # ── Inline edit form ──
            if st.session_state.get(edit_key, False):
                from datetime import date as _ed
                st.markdown("---")
                with st.form(f"edit_fam_form_{idx}"):
                    ec1, ec2 = st.columns(2)
                    with ec1:
                        ed_name = st.text_input(
                            "Full Name", value=r.get("beneficiary_name") or "",
                            key=f"ed_name_{idx}")
                        ed_phone = st.text_input(
                            "Phone", value=r.get("beneficiary_phone") or "",
                            key=f"ed_phone_{idx}")
                        _rel_opts = ["spouse", "parent", "child", "sibling", "guardian", "other"]
                        _cur_rel = r.get("relationship_type", "other")
                        _rel_idx = _rel_opts.index(_cur_rel) if _cur_rel in _rel_opts else 5
                        ed_rel = st.selectbox(
                            "Relationship", _rel_opts, index=_rel_idx,
                            key=f"ed_rel_{idx}")
                        ed_address = st.text_input(
                            "Address", value=r.get("beneficiary_address") or "",
                            key=f"ed_addr_{idx}")
                    with ec2:
                        _genders = ["male", "female", "other"]
                        _cur_g = (r.get("beneficiary_gender") or "other").lower()
                        _g_idx = _genders.index(_cur_g) if _cur_g in _genders else 2
                        ed_gender = st.selectbox(
                            "Gender", _genders, index=_g_idx,
                            key=f"ed_gender_{idx}")
                        _dob_val = None
                        if r.get("beneficiary_date_of_birth"):
                            try:
                                _dob_val = _ed.fromisoformat(str(r["beneficiary_date_of_birth"]))
                            except Exception:
                                _dob_val = _ed(1990, 1, 1)
                        else:
                            _dob_val = _ed(1990, 1, 1)
                        ed_dob = st.date_input(
                            "Date of Birth", value=_dob_val,
                            min_value=_ed(1920, 1, 1), max_value=_ed.today(),
                            key=f"ed_dob_{idx}")
                        _bg_opts = ["", "A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"]
                        _cur_bg = r.get("beneficiary_blood_group") or ""
                        _bg_idx = _bg_opts.index(_cur_bg) if _cur_bg in _bg_opts else 0
                        ed_blood = st.selectbox(
                            "Blood Group", _bg_opts, index=_bg_idx,
                            key=f"ed_blood_{idx}")
                        ed_ec_name = st.text_input(
                            "Emergency Contact Name",
                            value=r.get("beneficiary_emergency_contact_name") or "",
                            key=f"ed_ecn_{idx}")
                        ed_ec_phone = st.text_input(
                            "Emergency Contact Phone",
                            value=r.get("beneficiary_emergency_contact_phone") or "",
                            key=f"ed_ecp_{idx}")

                    b1, b2 = st.columns(2)
                    ed_save = b1.form_submit_button("💾 Save Changes", type="primary")
                    ed_cancel = b2.form_submit_button("Cancel")

                if ed_cancel:
                    st.session_state[edit_key] = False
                    st.rerun()

                if ed_save:
                    payload = {}
                    if ed_name.strip() and ed_name.strip() != (r.get("beneficiary_name") or ""):
                        payload["full_name"] = ed_name.strip()
                    if ed_phone.strip() != (r.get("beneficiary_phone") or ""):
                        payload["phone"] = ed_phone.strip()
                    if ed_gender != (r.get("beneficiary_gender") or "other").lower():
                        payload["gender"] = ed_gender
                    if str(ed_dob) != str(r.get("beneficiary_date_of_birth") or ""):
                        payload["date_of_birth"] = str(ed_dob)
                    if ed_blood != (r.get("beneficiary_blood_group") or ""):
                        payload["blood_group"] = ed_blood
                    if ed_address.strip() != (r.get("beneficiary_address") or ""):
                        payload["address"] = ed_address.strip()
                    if ed_ec_name.strip() != (r.get("beneficiary_emergency_contact_name") or ""):
                        payload["emergency_contact_name"] = ed_ec_name.strip()
                    if ed_ec_phone.strip() != (r.get("beneficiary_emergency_contact_phone") or ""):
                        payload["emergency_contact_phone"] = ed_ec_phone.strip()
                    if ed_rel != r.get("relationship_type", "other"):
                        payload["relationship_type"] = ed_rel

                    if not payload:
                        st.info("No changes detected.")
                    else:
                        try:
                            api.update_family_member(rel_id, payload)
                            st.success("✅ Family member updated!")
                            st.session_state[edit_key] = False
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed: {e}")

    if approved:
        for i, r in enumerate(approved):
            if r.get("relationship_type") == "self":
                continue
            family_count += 1
            _show_family_card(r, "✅", "Linked", i)

    if pending:
        for i, r in enumerate(pending):
            if r.get("relationship_type") == "self":
                continue
            family_count += 1
            _show_family_card(r, "⏳", "Pending", len(approved) + i)

    if family_count == 0:
        st.info("No family members added yet. Use the form below to add one.")

    # Add new family member — enter their details directly
    st.markdown("---")
    st.markdown("**Add a Family Member**")

    # ── UHID gate: patient must have their own ABHA/UHID before linking family ──
    my_uhid = p.get("abha_id")
    if not my_uhid:
        st.warning(
            "⚠️ You must set your own UHID (ABHA ID) in the profile form above "
            "before you can add family members. This is needed to establish the "
            "relationship between your records."
        )
        return  # stop here — don't show the family form

    st.caption("Enter their details below. They'll be registered and linked to your account so you can book for them.")

    with st.form("add_family_form"):
        fc1, fc2 = st.columns(2)
        with fc1:
            fam_name = st.text_input("Full Name *", placeholder="e.g. Sunita Kumar")
            fam_phone = st.text_input("Phone Number", placeholder="e.g. 9876543210")
            fam_relationship = st.selectbox("Relationship *",
                                             ["spouse", "parent", "child", "sibling", "guardian", "cousin","other"])


            if fam_relationship == "other":
                fam_relationship = st.text_input("Please specify relationship", placeholder="e.g. aunt, uncle, friend")
        with fc2:
            from datetime import date as _fam_d
            fam_dob = st.date_input("Date of Birth", value=_fam_d(1990, 1, 1),
                                     min_value=_fam_d(1920, 1, 1), max_value=_fam_d.today(),
                                     key="fam_dob")
            fam_gender = st.selectbox("Gender", ["male", "female", "other"], key="fam_gender")
            fam_blood = st.selectbox("Blood Group",
                                      ["", "A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"],
                                      key="fam_blood")

        fam_submitted = st.form_submit_button("👨‍👩‍👧 Add Family Member", use_container_width=True, type="primary")

    if fam_submitted:
        if not fam_name or len(fam_name.strip()) < 2:
            st.error("Please enter the family member's full name.")
        elif fam_relationship =='other' and not fam_relationship.strip():
            st.error("Please specify the relationship.")
        else:
            try:
                payload = {
                    "full_name": fam_name.strip(),
                    "relationship_type": fam_relationship,
                    "gender": fam_gender,
                    "date_of_birth": str(fam_dob),
                }
                if fam_phone:
                    payload["phone"] = fam_phone.strip()
                if fam_blood:
                    payload["blood_group"] = fam_blood
                result = api.add_family_member(payload)
                st.success(f"✅ {result.get('beneficiary_name', fam_name)} added as {fam_relationship}! You can now book appointments for them.")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to add family member: {e}")


# ════════════════════════════════════════════════════════════
# DOCTOR PAGES
# ════════════════════════════════════════════════════════════

def _get_my_doctor_sessions(active_only=True):
    """Get the logged-in doctor's sessions for today."""
    user = st.session_state.user
    try:
        from datetime import date
        today = str(date.today())
        for doc in api.list_doctors():
            if doc["user_id"] == user["id"]:
                sessions = api.get_doctor_sessions(doc["doctor_id"], from_date=today, to_date=today)
                if active_only:
                    return [s for s in sessions if s["status"] == "active"]
                return sessions
    except Exception:
        pass
    return []

def _get_my_doctor_session():
    """Get the selected doctor session (with picker if multiple)."""
    sessions = _get_my_doctor_sessions()
    if not sessions:
        return None
    if len(sessions) == 1:
        return sessions[0]["session_id"]
    # Multiple sessions — use session_state to track selection, show picker
    if st.session_state.get("doctor_session_id") and any(
        s["session_id"] == st.session_state["doctor_session_id"] for s in sessions
    ):
        return st.session_state["doctor_session_id"]
    # Default to first
    st.session_state["doctor_session_id"] = sessions[0]["session_id"]
    return sessions[0]["session_id"]

def _doctor_session_picker(sessions, key_prefix="doc"):
    """Show session picker for doctor if they have multiple sessions today."""
    if not sessions or len(sessions) <= 1:
        return
    labels = [
        f"{s['start_time'][:5]}–{s['end_time'][:5]} ({s.get('booked_count', 0)} patients)"
        for s in sessions
    ]
    current_idx = 0
    for i, s in enumerate(sessions):
        if s["session_id"] == st.session_state.get("doctor_session_id"):
            current_idx = i
            break
    sel = st.selectbox("🕐 Select Session", range(len(labels)),
                       format_func=lambda i: labels[i], index=current_idx,
                       key=f"{key_prefix}_sess_pick")
    if sessions[sel]["session_id"] != st.session_state.get("doctor_session_id"):
        st.session_state["doctor_session_id"] = sessions[sel]["session_id"]
        st.rerun()


def page_doctor_dashboard():
    """
    Doctor's main workspace.
    Step 1: Pick date  →  Step 2: Pick session  →  Step 3: See queue & act.

    Time-awareness:
      - Past sessions: read-only history (no buttons, no actions)
      - Today + active: full controls (call, complete, no-show, add patient)
      - Future: can activate/deactivate but no patient actions
    """
    from datetime import date as _dd, time as _time_cls

    tc1, tc2 = st.columns([6, 1])
    tc1.title("🩺 Doctor Dashboard")
    if tc2.button("🔄 Refresh", key="refresh_doc_dash", use_container_width=True):
        st.rerun()

    # ── Step 1: Date picker (persisted across refresh) ──
    user = st.session_state.user
    if "dd_picked_date" not in st.session_state:
        st.session_state["dd_picked_date"] = _dd.today()
    picked = st.date_input("Date", value=st.session_state["dd_picked_date"], key="dd_date")
    if picked != st.session_state["dd_picked_date"]:
        st.session_state["dd_picked_date"] = picked
        st.rerun()

    # ── Step 2: Fetch ALL sessions directly from DB (any status) ──
    all_sessions = _db_get_all_sessions_for_doctor(user["id"], str(picked))

    if not all_sessions:
        st.info(f"No sessions on {picked}.")
        return

    # ── Step 4: Session selectbox (like nurse) ──
    def _sess_label(s):
        t1 = str(s.get("start_time", ""))[:5]
        t2 = str(s.get("end_time", ""))[:5]
        status = s.get("status", "active").upper()
        booked = s.get("booked_count", 0)
        cap = s.get("total_slots", 0)
        try:
            hour = int(t1[:2])
        except Exception:
            hour = 9
        period = "Morning" if hour < 12 else ("Afternoon" if hour < 17 else "Evening")
        return f"{period} ({t1} - {t2}) | {booked}/{cap} patients | {status}"

    sess_labels = [_sess_label(s) for s in all_sessions]
    chosen_idx = st.selectbox(
        "Session", range(len(sess_labels)),
        format_func=lambda i: sess_labels[i],
        key="dd_sess_pick",
    )
    chosen_sess = all_sessions[chosen_idx]
    sid = chosen_sess["session_id"]
    sess_status = chosen_sess.get("status", "active")

    # ── Time awareness ──
    is_past    = picked < _dd.today()
    is_today   = picked == _dd.today()
    is_future  = picked > _dd.today()

    # ═══════════════════════════════════════════════════
    # SESSION STATUS CONTROLS
    # ─────────────────────────────────────────────────
    # Past date          → read-only history, no buttons
    # Cancelled/Completed→ message only
    # Inactive           → Activate button (no queue)
    # Active             → Deactivate button, full queue
    #
    # No auto-cancel / auto-complete. Doctor manually ends
    # session when leaving. Pending appointments stay until then.
    # ═══════════════════════════════════════════════════

    # ── Cancelled → dead end ──
    if sess_status == "cancelled":
        st.info("This session was **cancelled**.")
        return

    # ── Past date → fully read-only ──
    if is_past:
        status_label = sess_status.replace("_", " ").title()
        st.markdown(
            f'<div style="background:#f3f4f6;border-left:4px solid #9ca3af;padding:8px 14px;'
            f'border-radius:4px;margin-bottom:8px">'
            f'📅 <strong>Past session</strong> — was <strong>{status_label}</strong>. '
            f'Read-only view.</div>',
            unsafe_allow_html=True,
        )

    # ── Completed → just a note ──
    elif sess_status == "completed":
        st.caption("Session completed.")

    # ── Inactive → Activate button, no queue ──
    elif sess_status == "inactive":
        sc1, sc2 = st.columns([3, 1])
        sc1.warning("This session is **inactive** — patients cannot book yet.")
        if sc2.button("Activate", type="primary", key="activate_sess", use_container_width=True):
            try:
                api.activate_session({"session_id": sid})
                st.session_state["dd_msg"] = "✅ Session activated!"
                st.rerun()
            except Exception as ex:
                st.error(f"Could not activate: {ex}")
        return

    # ── Active → Deactivate button, queue below ──
    elif sess_status == "active":
        sc1, sc2 = st.columns([3, 1])
        sc1.success("Session is **active**.")
        if sc2.button("Deactivate", key="deact_sess", use_container_width=True):
            try:
                api.deactivate_session({"session_id": sid})
                st.session_state["dd_msg"] = "✅ Session deactivated."
                st.rerun()
            except Exception as ex:
                st.error(f"{ex}")

    st.divider()

    try:
        q = api.get_queue(sid)
    except Exception as e:
        st.error(f"Could not load queue: {e}")
        return

    s_start = str(q.get("session_start_time", ""))[:5]
    s_end = str(q.get("session_end_time", ""))[:5]
    dur = q.get("slot_duration_minutes", 15)
    all_q = q.get("queue", [])
    current_pat = q.get("current_patient")

    def _slot_t(entry):
        t = entry.get("original_slot_time", "")
        if t:
            return str(t)[:5]
        try:
            sh, sm = int(s_start[:2]), int(s_start[3:5])
            total = sh * 60 + sm + (entry.get("slot_number", 1) - 1) * dur
            return f"{total // 60:02d}:{total % 60:02d}"
        except Exception:
            return "-"

    # ── Metrics ──
    n_waiting = len([e for e in all_q if e["status"] == "checked_in"])
    n_booked = len([e for e in all_q if e["status"] == "booked"])
    n_done = q.get("completed_count", 0)
    n_noshow = len([e for e in all_q if e["status"] == "no_show"])

    delay_min = q.get("delay_minutes", 0) or 0
    delay_text = f" | ⏱️ Running {delay_min}min late" if delay_min > 0 else ""
    st.caption(f"Session {s_start} - {s_end} | {dur} min/slot{delay_text}")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Waiting", n_waiting)
    m2.metric("Booked", n_booked)
    m3.metric("Done", n_done)
    m4.metric("No-show", n_noshow)

    # ── Quick actions ──
    # Queue-management (check-in, extend, delay, end) → today + active only
    # Add Patient → today OR future + active (doctor can book emergency patients ahead)
    can_act_today = is_today and sess_status == "active"
    can_add_patient = (is_today or is_future) and sess_status == "active"

    # Show any pending messages from previous action
    if "dd_msg" in st.session_state:
        msg = st.session_state.pop("dd_msg")
        if msg.startswith("❌"):
            st.error(msg)
        elif msg.startswith("✖") or msg.startswith("⚠️"):
            st.warning(msg)
        else:
            st.success(msg)

    if can_act_today or can_add_patient:
        # Show all 5 columns but only enable relevant buttons
        ac1, ac2, ac3, ac4, ac5 = st.columns(5)
        with ac1:
            if can_act_today:
                if st.button("I'm Here", key="dash_checkin_btn", use_container_width=True):
                    try:
                        r = api.doctor_checkin({"session_id": sid})
                        st.success(r.get("message", "Checked in!"))
                        st.rerun()
                    except Exception as e:
                        st.error(f"{e}")
        with ac2:
            if st.button("Add Patient", key="dash_add_pat_btn", use_container_width=True):
                st.session_state["dd_show_add"] = not st.session_state.get("dd_show_add", False)
                st.rerun()
        with ac3:
            # Extend only available for afternoon sessions (start >= 14:00).
            # Morning pending patients auto-carry to afternoon on completion.
            _is_afternoon = False
            try:
                _is_afternoon = int(s_start[:2]) >= 14
            except Exception:
                pass
            if can_act_today and _is_afternoon:
                with st.popover("Extend", use_container_width=True):
                    with st.form("dash_ext", clear_on_submit=True):
                        try:
                            _dh, _dm = int(s_end[:2]), int(s_end[3:5])
                            _dv = _time_cls(min(_dh + ((_dm + 30) // 60), 23), (_dm + 30) % 60)
                        except Exception:
                            _dv = _time_cls(18, 0)
                        ne = st.time_input("New end time", value=_dv, key="d_ext_t")
                        nt = st.text_input("Reason", key="d_ext_n")
                        if st.form_submit_button("Extend"):
                            try:
                                api.extend_session({"session_id": sid, "new_end_time": str(ne), "note": nt})
                                st.rerun()
                            except Exception as e:
                                st.error(f"{e}")
            elif can_act_today and not _is_afternoon:
                st.caption("Pending patients carry over to afternoon session.")
        with ac4:
            if can_act_today:
                with st.popover("Running Late", use_container_width=True):
                    st.caption("Let patients know you are running behind schedule.")
                    with st.form("dash_del", clear_on_submit=True):
                        dl = st.number_input("Minutes late", 0, 120, q.get("delay_minutes", 0), key="d_del_m")
                        dr = st.text_input("Reason", key="d_del_r", placeholder="e.g. Emergency case")
                        if st.form_submit_button("Update"):
                            try:
                                api.update_delay({"session_id": sid, "delay_minutes": dl, "reason": dr})
                                st.rerun()
                            except Exception as e:
                                st.error(f"{e}")
        with ac5:
            if can_act_today:
                with st.popover("End Session", use_container_width=True):
                    st.caption("End this session. Doctor is leaving.")
                    warnings = []
                    if n_booked > 0:
                        warnings.append(f"{n_booked} booked → no-show")
                    if n_waiting > 0:
                        warnings.append(f"{n_waiting} checked-in → cancelled")
                    if current_pat:
                        st.error("A patient is currently **in progress**. Complete them first.")
                    else:
                        if warnings:
                            st.warning("Remaining: " + " | ".join(warnings))
                        cn = st.text_input("Note (optional)", key="d_comp_n")
                        if st.button("End Session", type="primary", key="d_comp_btn", use_container_width=True):
                            try:
                                api.complete_session({"session_id": sid, "note": cn})
                                st.rerun()
                            except Exception as e:
                                st.error(f"{e}")

    # ── Add Patient form (toggled) ──
    if can_add_patient and st.session_state.get("dd_show_add"):
        st.divider()
        st.subheader("Add Patient")
        if is_future:
            st.info(f"Booking for a future session on **{picked}**. Patient will receive a confirmation email.")

        # Build ALL time slots (doctor can pick any slot — their call)
        try:
            sh, sm = int(s_start[:2]), int(s_start[3:5])
        except Exception:
            sh, sm = 9, 0

        slot_counts = {}
        for e in all_q:
            sn = e.get("slot_number", 0)
            if e["status"] in ("booked", "checked_in", "in_progress", "completed"):
                slot_counts[sn] = slot_counts.get(sn, 0) + 1
        if current_pat:
            csn = current_pat.get("slot_number", 0)
            slot_counts[csn] = slot_counts.get(csn, 0) + 1

        total_slots = q.get("total_slots", 16)
        max_per_slot = q.get("max_patients_per_slot", 2)
        try:
            eh, em = int(s_end[:2]), int(s_end[3:5])
            end_min = eh * 60 + em
        except Exception:
            end_min = 23 * 60

        from datetime import datetime as _dt_now_cls
        now_min = _dt_now_cls.now().hour * 60 + _dt_now_cls.now().minute

        slot_opts = []
        default_idx = 0
        found_current = False
        for sn in range(1, total_slots + 1):
            t_min = sh * 60 + sm + (sn - 1) * dur
            if t_min >= end_min:
                continue
            t_label = f"{t_min // 60:02d}:{t_min % 60:02d}"
            count = slot_counts.get(sn, 0)
            # Only mark slots as past if session is today AND session is NOT active.
            # Active session → doctor is still working, all slots bookable.
            # Future date → never past.
            is_past_slot = is_today and sess_status != "active" and (t_min + dur <= now_min)

            if count >= max_per_slot:
                tag = f"FULL ({count}/{max_per_slot})"
                if is_past_slot:
                    tag = f"PAST · FULL ({count}/{max_per_slot})"
                slot_opts.append({"label": f"{t_label} — {tag}", "slot": sn, "full": True, "past": is_past_slot})
            elif is_past_slot:
                if count > 0:
                    slot_opts.append({"label": f"{t_label} — PAST · {count}/{max_per_slot} booked", "slot": sn, "full": False, "past": True})
                else:
                    slot_opts.append({"label": f"{t_label} — PAST · empty", "slot": sn, "full": False, "past": True})
            elif count > 0:
                slot_opts.append({"label": f"{t_label} — {count}/{max_per_slot} booked", "slot": sn, "full": False, "past": False})
            else:
                slot_opts.append({"label": f"{t_label} — Available", "slot": sn, "full": False, "past": False})

            # Default to first non-full current/future slot
            if not found_current and not is_past_slot and count < max_per_slot:
                default_idx = len(slot_opts) - 1
                found_current = True

        # Show ALL current/future slots — doctor picks any
        future_slots = [o for o in slot_opts if not o["past"]]
        if not future_slots:
            st.error("No current or future slots remaining in this session.")
            chosen_slot = None
            is_emergency_overbook = False
        else:
            slot_labels = [o["label"] for o in future_slots]
            # Default to first non-full slot
            default_pick = 0
            for idx, o in enumerate(future_slots):
                if not o["full"]:
                    default_pick = idx
                    break
            slot_idx = st.selectbox("Time Slot", range(len(slot_labels)),
                                    index=default_pick,
                                    format_func=lambda i: slot_labels[i], key="dd_add_slot")
            chosen_slot = future_slots[slot_idx]["slot"]
            is_emergency_overbook = future_slots[slot_idx]["full"]

            if is_emergency_overbook:
                st.warning(
                    f"This slot already has {max_per_slot} patients. "
                    f"Adding as **EMERGENCY** — patient will be marked CRITICAL priority. "
                    f"Extra {dur} min delay will propagate to subsequent appointments."
                )

        add_tab_new, add_tab_existing = st.tabs(["New Patient (Walk-in)", "Existing Patient"])

        with add_tab_new:
            with st.form("dd_new_pat", clear_on_submit=True):
                np1, np2 = st.columns(2)
                np_name = np1.text_input("Full Name *", key="dd_np_name")
                np_phone = np2.text_input("Phone *", key="dd_np_phone")

                np3, np4, np5 = st.columns(3)
                np_gender = np3.selectbox("Gender", ["male", "female", "other"], key="dd_np_gen")
                from datetime import date as _dd2
                np_dob = np4.date_input("Date of Birth", value=_dd2(1990, 1, 1), key="dd_np_dob",
                                        min_value=_dd2(1920, 1, 1), max_value=_dd2.today())
                np_blood = np5.selectbox("Blood Group", ["", "A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"], key="dd_np_blood")

                np6, np7 = st.columns(2)
                np_abha = np6.text_input("ABHA ID (optional)", key="dd_np_abha")
                np_address = np7.text_input("Address", key="dd_np_addr")

                st.caption("Emergency Contact")
                ec1, ec2 = st.columns(2)
                np_ec_name = ec1.text_input("Contact Name", key="dd_np_ec_name")
                np_ec_phone = ec2.text_input("Contact Phone", key="dd_np_ec_phone")

                if st.form_submit_button("Register & Book", type="primary", use_container_width=True):
                    if chosen_slot is None:
                        st.error("No slots available.")
                    elif not np_name or len(np_name.strip()) < 2:
                        st.error("Full name is required.")
                    elif not np_phone or len(np_phone.strip()) < 5:
                        st.error("Phone number is required.")
                    else:
                        try:
                            payload = {
                                "full_name": np_name.strip(),
                                "phone": np_phone.strip(),
                                "gender": np_gender,
                                "date_of_birth": str(np_dob),
                                "blood_group": np_blood or None,
                                "abha_id": np_abha.strip() or None,
                                "address": np_address.strip() or None,
                                "emergency_contact": np_ec_name.strip() or None,
                                "emergency_phone": np_ec_phone.strip() or None,
                                "session_id": sid,
                                "slot_number": chosen_slot,
                            }
                            if is_emergency_overbook:
                                payload["is_emergency"] = True
                                payload["priority_tier"] = "CRITICAL"
                            r = api.staff_register_book(payload)
                            label = f"{np_name} registered and booked!"
                            if is_emergency_overbook:
                                label += f" (Emergency overbook)"
                                # Propagate delay — extra patient means extra slot_duration delay
                                try:
                                    cur_delay = q.get("delay_minutes", 0) or 0
                                    new_delay = cur_delay + dur
                                    api.update_delay({
                                        "session_id": sid,
                                        "delay_minutes": new_delay,
                                        "reason": f"Emergency overbook: +{dur}min for extra patient",
                                    })
                                    label += f" | Delay updated to {new_delay}min"
                                except Exception:
                                    pass  # delay update is best-effort
                            st.session_state["dd_msg"] = f"✅ {label}"
                            st.session_state["dd_show_add"] = False
                            st.rerun()
                        except Exception as e:
                            st.error(f"{e}")

        with add_tab_existing:
            p_search = st.text_input("Search by name or phone", key="dd_p_search")
            if p_search and len(p_search) >= 2:
                try:
                    found = api.search_patients(p_search)
                    if not found:
                        st.info("No patients found. Use New Patient tab to register.")
                    for fp in found[:5]:
                        fp_name = fp.get("full_name", "Patient")
                        fp_age = f"{fp['age']}y" if fp.get("age") else ""
                        fp_phone = fp.get("phone", "")
                        fp_gender = (fp.get("gender", "")[:1].upper()) if fp.get("gender") else ""
                        fp_blood = fp.get("blood_group", "")
                        with st.container(border=True):
                            fc1, fc2 = st.columns([4, 1])
                            detail = f"**{fp_name}** | {fp_age} {fp_gender}"
                            if fp_phone:
                                detail += f" | {fp_phone}"
                            if fp_blood:
                                detail += f" | {fp_blood}"
                            fc1.write(detail)
                            if chosen_slot is None:
                                fc2.button("Book", key=f"dd_bk_{fp['patient_id']}", disabled=True)
                            elif fc2.button("Book", key=f"dd_bk_{fp['patient_id']}", use_container_width=True):
                                try:
                                    payload = {
                                        "session_id": sid,
                                        "patient_id": fp["patient_id"],
                                        "slot_number": chosen_slot,
                                    }
                                    if is_emergency_overbook:
                                        payload["is_emergency"] = True
                                        payload["priority_tier"] = "CRITICAL"
                                    r = api.staff_book(payload)
                                    label = f"{fp_name} booked!"
                                    if is_emergency_overbook:
                                        label += " (Emergency overbook)"
                                        try:
                                            cur_delay = q.get("delay_minutes", 0) or 0
                                            new_delay = cur_delay + dur
                                            api.update_delay({
                                                "session_id": sid,
                                                "delay_minutes": new_delay,
                                                "reason": f"Emergency overbook: +{dur}min for extra patient",
                                            })
                                            label += f" | Delay updated to {new_delay}min"
                                        except Exception:
                                            pass
                                    st.session_state["dd_msg"] = f"✅ {label}"
                                    st.session_state["dd_show_add"] = False
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"{e}")
                except Exception as e:
                    st.error(f"{e}")

    st.divider()

    # ── Current patient (only today + active) ──
    if can_act_today and current_pat:
        cp = current_pat
        cp_name = cp.get("patient_name") or "Patient"
        cp_age = f"{cp['patient_age']}y" if cp.get("patient_age") else ""
        st.subheader(f"With you now: {cp_name}")
        st.write(f"Slot #{cp['slot_number']} ({_slot_t(cp)}) | {cp_age} | Priority: {cp['priority_tier']}")

        b1, b2 = st.columns(2)
        cp_slot = cp.get("slot_number", 1)
        with b1:
            if st.button("Complete Visit", key="cp_complete", type="primary", use_container_width=True):
                try:
                    api.complete_appointment({"appointment_id": cp["appointment_id"]})
                    delay = _calc_and_update_delay(sid, s_start, dur, cp_slot)
                    msg = f"✅ {cp_name} visit completed."
                    if delay and delay > 0:
                        msg += f" Running {delay}min late."
                    elif delay == 0:
                        msg += " On schedule!"
                    st.session_state["dd_msg"] = msg
                    st.rerun()
                except Exception as e:
                    st.session_state["dd_msg"] = f"❌ Complete failed: {e}"
                    st.rerun()
        with b2:
            waiting_after = [e for e in all_q if e["status"] == "checked_in" and e["appointment_id"] != cp["appointment_id"]]
            if not waiting_after:
                st.button("Complete & Call Next", key="cp_call_next", use_container_width=True, disabled=True, help="No patients waiting")
            elif st.button("Complete & Call Next", key="cp_call_next", use_container_width=True):
                try:
                    api.complete_appointment({"appointment_id": cp["appointment_id"]})
                    delay = _calc_and_update_delay(sid, s_start, dur, cp_slot)
                    api.call_patient({"appointment_id": waiting_after[0]["appointment_id"]})
                    nxt_name = waiting_after[0].get("patient_name", "Next patient")
                    msg = f"✅ {cp_name} completed. {nxt_name} called in!"
                    if delay and delay > 0:
                        msg += f" Running {delay}min late."
                    elif delay == 0:
                        msg += " On schedule!"
                    st.session_state["dd_msg"] = msg
                    st.rerun()
                except Exception as e:
                    st.session_state["dd_msg"] = f"❌ Error: {e}"
                    st.rerun()
    elif can_act_today or can_add_patient:
        waiting_normal = [e for e in all_q if e["status"] == "checked_in" and not e.get("is_emergency")]
        waiting_emg = [e for e in all_q if e["status"] == "checked_in" and e.get("is_emergency")]
        booked = [e for e in all_q if e["status"] == "booked"]
        if waiting_emg:
            emg_p = waiting_emg[0]
            st.warning(f"🚨 Emergency: **{emg_p.get('patient_name', 'Patient')}** — Priority: {emg_p.get('priority_tier', 'CRITICAL')}")
            if can_act_today:
                dc1, dc2 = st.columns(2)
                if dc1.button("🚨 Call Emergency Patient", type="primary", key="dash_call_emg"):
                    try:
                        api.call_patient({"appointment_id": emg_p["appointment_id"]})
                        st.session_state["dd_msg"] = f"✅ Emergency patient {emg_p.get('patient_name', '')} called in!"
                        st.rerun()
                    except Exception as e:
                        st.session_state["dd_msg"] = f"❌ Call failed: {e}"
                        st.rerun()
                if waiting_normal:
                    nxt = waiting_normal[0]
                    if dc2.button(f"🔔 Call {nxt.get('patient_name', 'Next')}", key="dash_call_nxt_alt"):
                        try:
                            api.call_patient({"appointment_id": nxt["appointment_id"]})
                            st.session_state["dd_msg"] = f"✅ {nxt.get('patient_name', 'Patient')} called in!"
                            st.rerun()
                        except Exception as e:
                            st.session_state["dd_msg"] = f"❌ Call failed: {e}"
                            st.rerun()
        elif waiting_normal:
            nxt = waiting_normal[0]
            _nxt_slot_info = f"Slot #{nxt['slot_number']} ({_slot_t(nxt)})" if nxt.get("slot_number", 0) > 0 else ""
            st.info(f"Next: **{nxt.get('patient_name', 'Patient')}** {_nxt_slot_info}")
            if can_act_today:
                if st.button("Call Next Patient", type="primary", key="dash_call_nxt"):
                    try:
                        api.call_patient({"appointment_id": nxt["appointment_id"]})
                        st.session_state["dd_msg"] = f"✅ {nxt.get('patient_name', 'Patient')} called in!"
                        st.rerun()
                    except Exception as e:
                        st.session_state["dd_msg"] = f"❌ Call failed: {e}"
                        st.rerun()
        elif booked:
            st.info(f"**{len(booked)}** patient(s) booked, awaiting check-in. No one checked in yet.")
        else:
            st.caption("No patients in this session yet.")

    if can_act_today or can_add_patient:
        st.divider()

    # ── Patient Table (always shown — history or live) ──
    st.subheader("Patients" if (can_act_today or can_add_patient) else "Patient History")
    if not all_q:
        st.info("No patients in this session.")
    else:
        # ── Filters ──
        flt1, flt2, flt3 = st.columns(3)
        status_options = ["All"] + sorted({e["status"].replace("_", " ").title() for e in all_q})
        sel_status = flt1.selectbox("Filter by status", status_options, key="dd_flt_status")

        slot_set = sorted({e.get("slot_number", 0) for e in all_q})
        slot_labels = ["All Slots"] + [f"Slot {sn} ({_slot_t({'slot_number': sn})})" for sn in slot_set]
        sel_slot = flt2.selectbox("Filter by slot", slot_labels, key="dd_flt_slot")

        prio_options = ["All"] + sorted({e.get("priority_tier", "NORMAL") for e in all_q})
        sel_prio = flt3.selectbox("Filter by priority", prio_options, key="dd_flt_prio")

        sorted_q = sorted(all_q, key=lambda e: (e.get("slot_number", 0), e.get("slot_position", 0)))

        # Apply filters
        filtered_q = sorted_q
        if sel_status != "All":
            filtered_q = [e for e in filtered_q if e["status"].replace("_", " ").title() == sel_status]
        if sel_slot != "All Slots":
            try:
                sel_sn = int(sel_slot.split(" ")[1])
                filtered_q = [e for e in filtered_q if e.get("slot_number") == sel_sn]
            except Exception:
                pass
        if sel_prio != "All":
            filtered_q = [e for e in filtered_q if e.get("priority_tier", "NORMAL") == sel_prio]

        if not filtered_q:
            st.info("No patients match the selected filters.")
        else:
            # ── Table header ──
            hdr_cols = st.columns([0.6, 1.2, 2, 1, 1.3, 1.2, 2.5])
            hdr_cols[0].markdown("**Slot**")
            hdr_cols[1].markdown("**Time**")
            hdr_cols[2].markdown("**Patient**")
            hdr_cols[3].markdown("**Phone**")
            hdr_cols[4].markdown("**Status**")
            hdr_cols[5].markdown("**Priority**")
            hdr_cols[6].markdown("**Actions**")
            st.divider()

            for i, entry in enumerate(filtered_q):
                e_name = entry.get("patient_name") or "Patient"
                e_status = entry["status"]
                e_slot = entry.get("slot_number", "?")
                e_pos = entry.get("slot_position", 1)
                e_time = _slot_t(entry)
                e_prio = entry.get("priority_tier", "NORMAL")
                e_emerg = entry.get("is_emergency", False)
                e_appt_id = entry["appointment_id"]
                e_phone = entry.get("patient_phone", "") or ""

                icons = {"in_progress": "🔄", "checked_in": "⏳", "booked": "📅", "completed": "✅", "no_show": "🚫", "cancelled": "❌"}
                icon = icons.get(e_status, "⬜")
                status_label = e_status.replace("_", " ").title()
                prio_label = "🚨 CRITICAL" if e_emerg else e_prio

                # Slot label: show position if overbooked
                slot_label = f"{e_slot}" if e_pos <= 1 else f"{e_slot}.{e_pos}"

                # ── Table row ──
                row = st.columns([0.6, 1.2, 2, 1, 1.3, 1.2, 2.5])
                row[0].write(slot_label)
                row[1].write(e_time)
                row[2].write(f"**{e_name}**")
                row[3].write(e_phone[:10] if e_phone else "—")
                row[4].write(f"{icon} {status_label}")
                row[5].write(prio_label)

                # ── Actions column ──
                is_active_session = can_act_today or can_add_patient
                is_done = e_status in ("completed", "no_show", "cancelled")

                if not is_active_session or is_done:
                    row[6].write("—")
                elif e_status == "in_progress":
                    ac1, ac2 = row[6].columns(2)
                    if ac1.button("✅ Done", key=f"comp_{e_appt_id}", type="primary"):
                        try:
                            api.complete_appointment({"appointment_id": e_appt_id})
                            delay = _calc_and_update_delay(sid, s_start, dur, e_slot)
                            msg = f"✅ {e_name} visit completed."
                            if delay and delay > 0:
                                msg += f" Running {delay}min late."
                            elif delay == 0:
                                msg += " On schedule!"
                            st.session_state["dd_msg"] = msg
                            st.rerun()
                        except Exception as ex:
                            st.session_state["dd_msg"] = f"❌ Complete failed: {ex}"
                            st.rerun()
                    waiting_for_next = [e for e in all_q if e["status"] == "checked_in" and e["appointment_id"] != e_appt_id]
                    if not waiting_for_next:
                        ac2.button("➡️ Next", key=f"compnx_{e_appt_id}", disabled=True, help="No patients waiting")
                    elif ac2.button("➡️ Next", key=f"compnx_{e_appt_id}", help="Complete & call next"):
                        try:
                            api.complete_appointment({"appointment_id": e_appt_id})
                            delay = _calc_and_update_delay(sid, s_start, dur, e_slot)
                            api.call_patient({"appointment_id": waiting_for_next[0]["appointment_id"]})
                            nxt_name = waiting_for_next[0].get("patient_name", "Next patient")
                            msg = f"✅ {e_name} completed. {nxt_name} called in!"
                            if delay and delay > 0:
                                msg += f" Running {delay}min late."
                            elif delay == 0:
                                msg += " On schedule!"
                            st.session_state["dd_msg"] = msg
                            st.rerun()
                        except Exception as ex:
                            st.session_state["dd_msg"] = f"❌ Error: {ex}"
                            st.rerun()
                elif e_status == "checked_in":
                    has_in_progress = current_pat is not None
                    if has_in_progress:
                        ac1, ac2, ac3 = row[6].columns(3)
                        if ac1.button("⚡", key=f"prio_{e_appt_id}", help="Change priority"):
                            st.session_state[f"show_prio_{e_appt_id}"] = not st.session_state.get(f"show_prio_{e_appt_id}", False)
                            st.rerun()
                        if ac2.button("❌", key=f"canc_{e_appt_id}", help="Cancel appointment"):
                            st.session_state[f"show_cancel_{e_appt_id}"] = not st.session_state.get(f"show_cancel_{e_appt_id}", False)
                            st.rerun()
                        if ac3.button("🚫", key=f"ns_{e_appt_id}", help="No-show"):
                            if _mark_noshow(e_appt_id):
                                st.session_state["dd_msg"] = f"✅ {e_name} marked no-show."
                                st.rerun()
                            else:
                                st.session_state["dd_msg"] = f"❌ Could not mark no-show"
                                st.rerun()
                    else:
                        ac1, ac2, ac3, ac4 = row[6].columns(4)
                        if ac1.button("📞", key=f"call_{e_appt_id}", help="Call in"):
                            try:
                                api.call_patient({"appointment_id": e_appt_id})
                                st.session_state["dd_msg"] = f"✅ {e_name} called in!"
                                st.rerun()
                            except Exception as ex:
                                st.session_state["dd_msg"] = f"❌ Call failed: {ex}"
                                st.rerun()
                        if ac2.button("⚡", key=f"prio2_{e_appt_id}", help="Change priority"):
                            st.session_state[f"show_prio_{e_appt_id}"] = not st.session_state.get(f"show_prio_{e_appt_id}", False)
                            st.rerun()
                        if ac3.button("❌", key=f"canc2_{e_appt_id}", help="Cancel"):
                            st.session_state[f"show_cancel_{e_appt_id}"] = not st.session_state.get(f"show_cancel_{e_appt_id}", False)
                            st.rerun()
                        if ac4.button("🚫", key=f"ns2_{e_appt_id}", help="No-show"):
                            if _mark_noshow(e_appt_id):
                                st.session_state["dd_msg"] = f"✅ {e_name} marked no-show."
                                st.rerun()
                            else:
                                st.session_state["dd_msg"] = f"❌ Could not mark no-show"
                                st.rerun()
                elif e_status == "booked":
                    ac1, ac2, ac3 = row[6].columns(3)
                    if ac1.button("⚡", key=f"prio3_{e_appt_id}", help="Change priority"):
                        st.session_state[f"show_prio_{e_appt_id}"] = not st.session_state.get(f"show_prio_{e_appt_id}", False)
                        st.rerun()
                    if ac2.button("❌", key=f"canc3_{e_appt_id}", help="Cancel appointment"):
                        st.session_state[f"show_cancel_{e_appt_id}"] = not st.session_state.get(f"show_cancel_{e_appt_id}", False)
                        st.rerun()
                    if ac3.button("🚫", key=f"bns_{e_appt_id}", help="No-show"):
                        if _mark_noshow(e_appt_id):
                            st.session_state["dd_msg"] = f"✅ {e_name} marked no-show."
                            st.rerun()
                        else:
                            st.session_state["dd_msg"] = f"❌ Could not mark no-show"
                            st.rerun()
                else:
                    row[6].write("—")

                # ── Priority edit (expanded inline when toggled) ──
                if is_active_session and st.session_state.get(f"show_prio_{e_appt_id}", False) and e_status in ("checked_in", "booked"):
                    with st.container():
                        with st.form(f"prioform_{e_appt_id}", clear_on_submit=True):
                            pc1, pc2, pc3, pc4 = st.columns([1.5, 1, 2, 1])
                            tier_opts = ["NORMAL", "HIGH", "CRITICAL"]
                            cur_idx = tier_opts.index(e_prio) if e_prio in tier_opts else 0
                            new_tier = pc1.selectbox("Tier", tier_opts, index=cur_idx, key=f"pt_{e_appt_id}")
                            new_emerg = pc2.checkbox("Emergency", value=e_emerg, key=f"em_{e_appt_id}")
                            esc_reason = pc3.text_input("Reason", key=f"er_{e_appt_id}")
                            if pc4.form_submit_button("Save"):
                                try:
                                    api.escalate_priority({
                                        "appointment_id": e_appt_id,
                                        "priority_tier": new_tier,
                                        "is_emergency": new_emerg,
                                        "reason": esc_reason or "Updated by doctor",
                                    })
                                    st.session_state[f"show_prio_{e_appt_id}"] = False
                                    st.session_state["dd_msg"] = f"✅ Priority updated for {e_name}."
                                    st.rerun()
                                except Exception as ex:
                                    st.session_state["dd_msg"] = f"❌ Priority update failed: {ex}"
                                    st.session_state[f"show_prio_{e_appt_id}"] = False
                                    st.rerun()

                # ── Cancel confirmation (expanded inline when toggled) ──
                if is_active_session and st.session_state.get(f"show_cancel_{e_appt_id}", False) and e_status in ("checked_in", "booked"):
                    with st.container():
                        st.warning(f"Cancel appointment for **{e_name}** (Slot {slot_label} at {e_time})?")
                        cc1, cc2, cc3 = st.columns([2, 1, 1])
                        cancel_reason = cc1.text_input("Reason", key=f"cr_{e_appt_id}", placeholder="e.g. Patient request, Emergency reschedule")
                        if cc2.button("Confirm Cancel", key=f"cc_{e_appt_id}", type="primary"):
                            try:
                                api.staff_cancel_appointment({
                                    "appointment_id": e_appt_id,
                                    "reason": cancel_reason or "Cancelled by doctor",
                                })
                                st.session_state[f"show_cancel_{e_appt_id}"] = False
                                st.session_state["dd_msg"] = f"✅ {e_name}'s appointment cancelled."
                                st.rerun()
                            except Exception as ex:
                                st.session_state["dd_msg"] = f"❌ Cancel failed: {ex}"
                                st.rerun()
                        if cc3.button("Keep", key=f"ck_{e_appt_id}"):
                            st.session_state[f"show_cancel_{e_appt_id}"] = False
                            st.rerun()


def _show_patient_detail(entry):
    """Render patient detail card inside an expander or popover."""
    name = entry.get("patient_name") or "Patient"
    age = f"{entry['patient_age']}y" if entry.get("patient_age") else "—"
    gender = entry.get("patient_gender", "—") or "—"
    blood = entry.get("patient_blood_group", "—") or "—"
    phone = entry.get("patient_phone", "—") or "—"
    addr = entry.get("patient_address", "—") or "—"
    ec_name = entry.get("patient_emergency_contact", "—") or "—"
    ec_phone = entry.get("patient_emergency_phone", "—") or "—"
    risk = entry.get("patient_risk_score")
    abha = entry.get("patient_abha_id", "—") or "—"
    prio = entry.get("priority_tier", "NORMAL")
    vis = entry.get("visual_priority", 5)
    emerg = entry.get("is_emergency", False)

    st.markdown(f"**{name}**")
    d1, d2, d3 = st.columns(3)
    d1.markdown(f"**Age:** {age}")
    d2.markdown(f"**Gender:** {gender}")
    d3.markdown(f"**Blood:** {blood}")

    d4, d5 = st.columns(2)
    d4.markdown(f"**Phone:** {phone}")
    d5.markdown(f"**ABHA:** {abha}")

    if addr != "—":
        st.markdown(f"**Address:** {addr}")

    e1, e2 = st.columns(2)
    e1.markdown(f"**Emergency Contact:** {ec_name}")
    e2.markdown(f"**Emergency Phone:** {ec_phone}")

    p1, p2, p3 = st.columns(3)
    p1.markdown(f"**Priority:** {prio}")
    p2.markdown(f"**Urgency:** {vis}/10")
    if emerg:
        p3.markdown("**🚨 EMERGENCY**")
    if risk is not None:
        st.markdown(f"**Risk Score:** {risk}")


def page_doctor_queue():
    tc1, tc2 = st.columns([6, 1])
    tc1.title("📋 My Queue")
    if tc2.button("🔄 Refresh", key="refresh_doc_queue", use_container_width=True):
        st.session_state.pop("doctor_session_id", None)
        st.rerun()

    # Auto-refresh for doctor queue
    auto_ref_doc = st.sidebar.toggle("Auto-refresh (30s)", value=False, key="auto_ref_doc_queue")
    if auto_ref_doc:
        import streamlit.components.v1 as components
        components.html(
            '<script>setTimeout(function(){window.parent.location.reload()}, 30000);</script>',
            height=0,
        )

    # Session picker (if multiple sessions today)
    my_sessions = _get_my_doctor_sessions()
    if not my_sessions:
        st.info("No active session today."); return
    _doctor_session_picker(my_sessions, "queue")
    sid = _get_my_doctor_session()
    if not sid:
        st.info("No active session today."); return
    try:
        q = api.get_queue(sid)
    except Exception as e:
        st.error(f"Could not load queue: {e}"); return

    all_doc_entries = q.get("queue", [])
    doc_waiting = [e for e in all_doc_entries if e["status"] == "checked_in"]
    doc_not_arrived = [e for e in all_doc_entries if e["status"] == "booked"]
    doc_default_dur = q.get("slot_duration_minutes", 15)

    # Time-awareness for doctor page
    from datetime import date as _date_doc
    doc_session_date = q.get("session_date", "")
    doc_session_start = str(q.get("session_start_time", ""))[:5]
    doc_session_end = str(q.get("session_end_time", ""))[:5]
    try:
        doc_sd = _date_doc.fromisoformat(doc_session_date) if doc_session_date else _date_doc.today()
    except Exception:
        doc_sd = _date_doc.today()
    doc_is_past = doc_sd < _date_doc.today()
    doc_is_today = doc_sd == _date_doc.today()
    doc_is_future = doc_sd > _date_doc.today()

    # ── Session info banner with date, year, time range ──
    doc_date_display = doc_sd.strftime("%A, %B %d, %Y")
    doc_name_display = q.get("doctor_name", "")
    st.markdown(
        f'<div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:8px;padding:10px 16px;margin-bottom:12px">'
        f'<span style="font-size:1.05em">📆 <strong>{doc_date_display}</strong></span>'
        f'&nbsp;&nbsp;•&nbsp;&nbsp;🕐 <strong>{doc_session_start} – {doc_session_end}</strong>'
        f'&nbsp;&nbsp;•&nbsp;&nbsp;🩺 <strong>{doc_name_display}</strong>'
        f'</div>',
        unsafe_allow_html=True,
    )

    if doc_is_past:
        st.markdown(
            '<div style="background:#fef2f2;border-left:4px solid #ef4444;padding:8px 14px;'
            'border-radius:4px;margin-bottom:12px">⏰ <strong>Past session</strong> — '
            'review only. Complete any remaining patients to close the session.</div>',
            unsafe_allow_html=True,
        )
    elif doc_is_future:
        st.info("🕐 This session is in the future. Actions will be available on the session date.")

    # Helper: slot time for doctor queue
    def _doc_slot_time(entry):
        t = entry.get("original_slot_time", "")
        if t:
            return str(t)[:5]
        try:
            sh, sm = int(doc_session_start[:2]), int(doc_session_start[3:5])
            sn = entry.get("slot_number", 1)
            total_min = sh * 60 + sm + (sn - 1) * doc_default_dur
            return f"{total_min // 60:02d}:{total_min % 60:02d}"
        except Exception:
            return "—"

    # ── Helper: format patient details line ──
    def _doc_patient_detail(entry):
        age = f"{entry['patient_age']}y" if entry.get("patient_age") else ""
        gen = f"/{entry['patient_gender'][:1].upper()}" if entry.get("patient_gender") else ""
        bg = f"  •  🩸 {entry['patient_blood_group']}" if entry.get("patient_blood_group") else ""
        phone = f"  •  📞 {entry['patient_phone']}" if entry.get("patient_phone") else ""
        age_str = f"👤 {age}{gen}" if age else ""
        return f"{age_str}{bg}{phone}"

    # ── Summary metrics ──
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("⏳ Waiting", len(doc_waiting))
    mc2.metric("📅 Not Arrived", len(doc_not_arrived))
    mc3.metric("✔️ Completed", len([e for e in all_doc_entries if e["status"] == "completed"]))
    mc4.metric("⏱️ Delay", f"{q.get('delay_minutes', 0)} min")

    st.divider()

    # ═══════════════════════════════════════════════
    # CURRENT PATIENT (with doctor right now)
    # ═══════════════════════════════════════════════
    if q.get("current_patient"):
        cp = q["current_patient"]
        cp_time = _doc_slot_time(cp)
        cp_name = cp.get('patient_name') or 'Patient'
        cp_detail = _doc_patient_detail(cp)

        st.markdown(
            f'<div style="background:#f5f3ff;border:2px solid #8b5cf6;border-radius:10px;padding:14px 18px;margin-bottom:16px">'
            f'<div style="font-size:0.8em;color:#7c3aed;font-weight:600;margin-bottom:6px">🔄 CURRENTLY WITH YOU</div>'
            f'<div style="font-size:1.2em;font-weight:700;color:#1e1b4b">{cp_name}</div>'
            f'<div style="display:flex;flex-wrap:wrap;gap:16px;font-size:0.9em;color:#4c1d95;margin-top:6px">'
            f'<span>🕐 <strong>{cp_time}</strong></span>'
            f'<span>🎫 Slot #{cp["slot_number"]}</span>'
            f'<span>⚡ {cp["priority_tier"]}</span>'
            + (f'<span>{cp_detail}</span>' if cp_detail else '')
            + f'</div></div>',
            unsafe_allow_html=True,
        )
        if not doc_is_future:
            notes = st.text_input("Visit notes (optional)", key="doc_notes")
            bc1, bc2 = st.columns([4, 1])
            if bc1.button("✅ Mark Complete", type="primary", use_container_width=True):
                try:
                    r = api.complete_appointment({"appointment_id": cp["appointment_id"], "notes": notes})
                    st.success(r["message"])
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
            if bc2.button("↩ Send Back", key="doc_undo_send", use_container_width=True):
                try:
                    r = api.undo_send({"session_id": sid})
                    st.success(f"↩ {cp_name} sent back to queue.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
    else:
        # No current patient — show Call Next prominently if there are waiting patients
        if doc_waiting and not doc_is_future:
            next_p = doc_waiting[0]
            next_name = next_p.get("patient_name") or "Patient"
            next_time = _doc_slot_time(next_p)
            st.markdown(
                f'<div style="background:#fef3c7;border:2px solid #f59e0b;border-radius:10px;padding:14px 18px;margin-bottom:12px">'
                f'<div style="font-size:0.8em;color:#92400e;font-weight:600;margin-bottom:4px">📢 NO PATIENT WITH YOU — READY TO CALL NEXT</div>'
                f'<div style="font-size:1.1em;color:#78350f">Next up: <strong>{next_name}</strong> (🕐 {next_time})</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if st.button(f"📢 Call {next_name} In", type="primary", use_container_width=True, key="doc_call_next_top"):
                try:
                    r = api.call_next({"session_id": sid})
                    st.success(r["message"])
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
        elif doc_is_future:
            st.info("🕐 Session hasn't started yet — actions available on session date.")
        else:
            st.success("No patients waiting. Queue is empty!")

    # ═══════════════════════════════════════════════
    # WAITING LIST (checked in, ordered by priority)
    # ═══════════════════════════════════════════════
    if doc_waiting:
        st.divider()
        st.markdown(f"### ⏳ Waiting Queue ({len(doc_waiting)})")
        if q.get("delay_minutes", 0) > 0:
            st.warning(f"⏱️ Running {q['delay_minutes']} min behind schedule")

        for idx, entry in enumerate(doc_waiting):
            priority_dot = {"CRITICAL": "🔴", "HIGH": "🟠", "NORMAL": "🟢"}.get(entry["priority_tier"], "⚪")
            emergency = " 🚨" if entry.get("is_emergency") else ""
            e_time = _doc_slot_time(entry)
            e_name = entry.get('patient_name') or 'Patient'
            e_detail = _doc_patient_detail(entry)

            # First patient gets "NEXT" badge
            if idx == 0:
                badge = '<span style="background:#f59e0b;color:white;padding:2px 8px;border-radius:10px;font-size:0.75em;font-weight:600;margin-left:8px">NEXT</span>'
            else:
                badge = f'<span style="background:#e5e7eb;color:#4b5563;padding:2px 8px;border-radius:10px;font-size:0.75em;margin-left:8px">#{idx + 1}</span>'

            with st.container(border=True):
                st.markdown(
                    f'{priority_dot} **{e_name}**{emergency} {badge}'
                    f'&nbsp;&nbsp;|&nbsp;&nbsp;🕐 **{e_time}**'
                    f'&nbsp;&nbsp;|&nbsp;&nbsp;Slot #{entry["slot_number"]}',
                    unsafe_allow_html=True,
                )
                st.caption(f"{e_detail}  •  Priority: {entry['priority_tier']}  •  Urgency: {entry['visual_priority']}/10" if e_detail else f"Priority: {entry['priority_tier']}  •  Urgency: {entry['visual_priority']}/10")

    # ═══════════════════════════════════════════════
    # NOT YET ARRIVED (booked, waiting for check-in)
    # ═══════════════════════════════════════════════
    if doc_not_arrived:
        st.divider()
        st.markdown(f"### 📅 Not Yet Arrived ({len(doc_not_arrived)})")
        for entry in doc_not_arrived:
            e_time = _doc_slot_time(entry)
            e_name = entry.get('patient_name') or 'Patient'
            e_detail = _doc_patient_detail(entry)
            with st.container(border=True):
                st.markdown(f"📅 **{e_name}**  |  🕐 **{e_time}**  |  Slot #{entry['slot_number']}")
                st.caption(f"{e_detail}  •  Booked — waiting for nurse check-in" if e_detail else "Booked — waiting for nurse check-in")

    # ═══════════════════════════════════════════════
    # COMPLETED (doctor can undo today)
    # ═══════════════════════════════════════════════
    doc_completed = [e for e in all_doc_entries if e["status"] == "completed"]
    if doc_completed:
        st.divider()
        with st.expander(f"✔️ Completed ({len(doc_completed)})", expanded=False):
            for entry in doc_completed:
                e_time = _doc_slot_time(entry)
                e_name = entry.get('patient_name') or 'Patient'
                completed_at = entry.get("completed_at", "")
                c_str = f"  •  Done at {str(completed_at)[11:16]}" if completed_at else ""
                with st.container(border=True):
                    c1, c2 = st.columns([6, 1])
                    c1.markdown(f"✔️ **{e_name}**  |  🕐 {e_time}  |  Slot #{entry['slot_number']}{c_str}")
                    if doc_is_today:
                        if c2.button("↩ Undo", key=f"doc_undo_comp_{entry['appointment_id']}"):
                            try:
                                r = api.undo_complete({"appointment_id": entry["appointment_id"]})
                                st.success(f"↩ {e_name} moved back to With Doctor.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")

    # ═══════════════════════════════════════════════
    # NO-SHOWS
    # ═══════════════════════════════════════════════
    doc_noshows = [e for e in all_doc_entries if e["status"] == "no_show"]
    if doc_noshows:
        st.divider()
        with st.expander(f"⚠️ No-Shows ({len(doc_noshows)})", expanded=False):
            for entry in doc_noshows:
                e_time = _doc_slot_time(entry)
                e_name = entry.get('patient_name') or 'Patient'
                st.markdown(f"⚠️ **{e_name}**  |  🕐 {e_time}  |  Slot #{entry['slot_number']}")


def page_doctor_session():
    tc1, tc2 = st.columns([6, 1])
    tc1.title("⚙️ Session Controls")
    if tc2.button("🔄 Refresh", key="refresh_doc_session", use_container_width=True):
        st.session_state.pop("doctor_session_id", None)
        st.rerun()
    my_sessions = _get_my_doctor_sessions()
    if not my_sessions:
        st.info("No active session today."); return
    _doctor_session_picker(my_sessions, "ctrl")
    sid = _get_my_doctor_session()
    if not sid:
        st.info("No active session today."); return

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Check-in")
        st.caption("Press when you arrive at clinic. Auto-calculates if you're late.")
        if st.button("🏥 I'm Here", type="primary", use_container_width=True):
            try:
                r = api.doctor_checkin({"session_id": sid})
                st.success(r["message"])
            except Exception as e:
                st.error(f"{e}")
    with c2:
        st.subheader("Update Delay")
        st.caption("If you're running behind, update so patients see new times.")
        with st.form("delay_form"):
            delay = st.number_input("Minutes behind", min_value=0, max_value=120, value=0)
            reason = st.text_input("Reason (optional)")
            if st.form_submit_button("Update"):
                try:
                    r = api.update_delay({"session_id": sid, "delay_minutes": delay, "reason": reason})
                    st.success(r["message"])
                except Exception as e:
                    st.error(f"{e}")

    # Determine if this is an afternoon session (start >= 14:00)
    _sess_is_afternoon = False
    for _ms in my_sessions:
        if _ms["session_id"] == sid:
            try:
                _sess_is_afternoon = int(str(_ms["start_time"])[:2]) >= 14
            except Exception:
                pass
            break

    st.divider()
    if _sess_is_afternoon:
        c3, c4 = st.columns(2)
        with c3:
            st.subheader("Overtime Check")
            st.caption("See how many patients you can still see if you stay extra.")
            with st.form("ot_form"):
                ot = st.number_input("Extra minutes you can stay", min_value=0, max_value=60, value=15)
                if st.form_submit_button("Check"):
                    try:
                        r = api.overtime_window({"session_id": sid, "overtime_minutes": ot})
                        st.info(r["message"])
                        for p in r.get("patients_can_be_seen", []):
                            st.write(f"  ✅ {(p.get('patient_name') or '?')} — Slot {p['slot_number']}")
                        for p in r.get("patients_cannot_be_seen", []):
                            st.write(f"  ❌ {(p.get('patient_name') or '?')} — Slot {p['slot_number']} (will be notified)")
                    except Exception as e:
                        st.error(f"{e}")
        with c4:
            st.subheader("Extend Session")
            st.caption("Officially extend your session end time to see more patients.")
            with st.form("extend_form"):
                new_end = st.time_input("New end time")
                note = st.text_input("Reason")
                if st.form_submit_button("Extend"):
                    try:
                        r = api.extend_session({"session_id": sid, "new_end_time": str(new_end), "note": note})
                        st.toast(r.get('message', 'Session extended!'), icon="✅")
                        st.rerun()
                    except Exception as e:
                        st.error(f"{e}")
    else:
        st.info("☀️ **Morning session** — Extend/Overtime not available. "
                "Pending patients will automatically carry over to the afternoon session when you complete this one.")


# ════════════════════════════════════════════════════════════
# NURSE / ADMIN — SINGLE "SESSION & QUEUE" PAGE
# ════════════════════════════════════════════════════════════

def page_staff_session():
    """
    Nurse's main workspace — real-time patient management.
    Flow: Department → Doctor → See all patients → Click patient → Take action.
    """
    from datetime import datetime, date as _date_type
    import time as _time

    tc1, tc2 = st.columns([6, 1])
    tc1.title("📋 Nurse Station")
    if tc2.button("🔄 Refresh", key="refresh_nurse", use_container_width=True):
        st.rerun()

    # Show success/error from previous action
    if "dd_msg" in st.session_state:
        _dd = st.session_state.pop("dd_msg")
        if _dd.startswith("❌"):
            st.error(_dd)
        elif _dd.startswith("✖") or _dd.startswith("⚠️"):
            st.warning(_dd)
        else:
            st.success(_dd)

    # ── Step 1: Department → Doctor → Session picker ──
    session_id = _smart_session_picker("staff_sp")
    if not session_id:
        return

    # Auto-refresh
    auto_refresh = st.sidebar.toggle("Auto-refresh (30s)", value=False, key="auto_ref_toggle")
    if auto_refresh:
        import streamlit.components.v1 as components
        components.html(
            '<script>setTimeout(function(){window.parent.location.reload()}, 30000);</script>',
            height=0,
        )

    # ── Load queue data ──
    try:
        q = api.get_queue(session_id)
    except Exception as e:
        st.error(f"Could not load queue: {e}"); return

    # ── Time awareness ──
    session_date_str = q.get("session_date", "")
    try:
        s_date = _date_type.fromisoformat(session_date_str)
    except Exception:
        s_date = _date_type.today()
    is_past = s_date < _date_type.today()
    is_today = s_date == _date_type.today()
    is_future = s_date > _date_type.today()

    doctor_name = q.get("doctor_name", "Doctor")
    default_dur = q.get("slot_duration_minutes", 15)
    session_start = q.get("session_start_time", "")
    session_end = q.get("session_end_time", "")
    nurse_sess_status = q.get("session_status", "active")

    # ── Gather all patients ──
    all_entries = q.get("queue", [])
    current_patient = q.get("current_patient")
    # Separate emergency (slot_number=0) from normal queue
    waiting = [e for e in all_entries if e["status"] == "checked_in" and not e.get("is_emergency")]
    emergency_waiting = [e for e in all_entries if e["status"] == "checked_in" and e.get("is_emergency")]
    not_arrived = [e for e in all_entries if e["status"] == "booked"]
    completed_entries = [e for e in all_entries if e["status"] == "completed"]
    noshow_entries = [e for e in all_entries if e["status"] == "no_show"]
    # Merge all into one unified list
    all_patients = []
    if current_patient:
        all_patients.append(current_patient)
    all_patients.extend(emergency_waiting)
    all_patients.extend(waiting)
    all_patients.extend(not_arrived)
    all_patients.extend(completed_entries)
    all_patients.extend(noshow_entries)

    # ── Header bar ──
    ref_col, deact_col, ts_col = st.columns([1, 1, 3])
    if ref_col.button("🔄 Refresh", key="staff_refresh"):
        st.rerun()
    # Deactivate / Activate toggle for current session
    if nurse_sess_status == "active":
        if deact_col.button("🔴 Deactivate", key="nurse_deact_sess", use_container_width=True):
            try:
                api.deactivate_session({"session_id": session_id})
                st.session_state["dd_msg"] = "✅ Session deactivated."
                st.rerun()
            except Exception as e:
                st.session_state["dd_msg"] = f"❌ {e}"
                st.rerun()
    elif nurse_sess_status == "inactive":
        if deact_col.button("🟢 Activate", key="nurse_act_sess", use_container_width=True):
            try:
                api.activate_session({"session_id": session_id})
                st.session_state["dd_msg"] = "✅ Session activated."
                st.rerun()
            except Exception as e:
                st.session_state["dd_msg"] = f"❌ {e}"
                st.rerun()
    ts_col.caption(f"**{doctor_name}**  •  {session_date_str}  •  {session_start[:5]}–{session_end[:5]}  •  Updated {datetime.now().strftime('%I:%M %p')}")

    if is_past:
        st.markdown(
            '<div style="background:#fef2f2;border-left:4px solid #ef4444;padding:8px 14px;'
            'border-radius:4px;margin-bottom:10px">⏰ <strong>Past session</strong> — '
            'You can mark remaining patients as completed or no-show.</div>',
            unsafe_allow_html=True,
        )
    elif is_future:
        st.info("🕐 Future session — limited actions available until session date.")

    # ── Status summary (colored pills) ──
    n_booked = len(not_arrived)
    n_waiting = len(waiting)
    n_emergency = len(emergency_waiting)
    n_ip = 1 if current_patient else 0
    n_done = len(completed_entries)
    n_noshow = len(noshow_entries)
    total_p = n_booked + n_waiting + n_emergency + n_ip + n_done + n_noshow
    progress = (n_done / total_p * 100) if total_p > 0 else 0

    emg_pill = ""
    if n_emergency > 0:
        emg_pill = (f'<div style="background:#dc262620;border:1px solid #dc262650;border-radius:20px;padding:4px 14px;font-size:0.85em">'
                    f'🚨 <strong>{n_emergency}</strong> Emergency</div>')

    summary_html = (
        '<div style="display:flex;gap:6px;margin:6px 0 12px 0;flex-wrap:wrap;align-items:center">'
        f'<div style="background:#3b82f620;border:1px solid #3b82f650;border-radius:20px;padding:4px 14px;font-size:0.85em">'
        f'📅 <strong>{n_booked}</strong> Booked</div>'
        f'{emg_pill}'
        f'<div style="background:#f59e0b20;border:1px solid #f59e0b50;border-radius:20px;padding:4px 14px;font-size:0.85em">'
        f'✅ <strong>{n_waiting}</strong> Waiting</div>'
        f'<div style="background:#8b5cf620;border:1px solid #8b5cf650;border-radius:20px;padding:4px 14px;font-size:0.85em">'
        f'🔄 <strong>{n_ip}</strong> With Doctor</div>'
        f'<div style="background:#22c55e20;border:1px solid #22c55e50;border-radius:20px;padding:4px 14px;font-size:0.85em">'
        f'✔️ <strong>{n_done}</strong> Done</div>'
        f'<div style="background:#ef444420;border:1px solid #ef444450;border-radius:20px;padding:4px 14px;font-size:0.85em">'
        f'⚠️ <strong>{n_noshow}</strong> No-Show</div>'
        f'<div style="margin-left:auto;font-size:0.85em;color:#6b7280">{n_done}/{total_p} ({progress:.0f}%)</div>'
        '</div>'
    )
    st.markdown(summary_html, unsafe_allow_html=True)

    # Progress bar
    prog_color = "#22c55e" if progress >= 80 else "#f59e0b" if progress >= 40 else "#3b82f6"
    st.markdown(
        f'<div style="background:#e5e7eb;border-radius:4px;height:6px;margin-bottom:12px">'
        f'<div style="background:{prog_color};width:{progress:.0f}%;height:6px;border-radius:4px"></div></div>',
        unsafe_allow_html=True,
    )

    # ── Quick action bar ──
    qa1, qa2, qa3, qa4 = st.columns(4)

    # Call Next (normal queue)
    if not is_future and not current_patient and waiting:
        next_name = (waiting[0].get("patient_name") or "Next Patient")
        if qa1.button(f"🔔 Call {next_name}", type="primary", use_container_width=True, key="call_next_top"):
            try:
                r = api.call_patient({"appointment_id": waiting[0]["appointment_id"]})
                st.session_state["dd_msg"] = r.get("message", f"✅ {next_name} called in!")
                st.rerun()
            except Exception as e:
                st.session_state["dd_msg"] = f"❌ {e}"
                st.rerun()
    elif current_patient:
        qa1.info(f"🔄 {(current_patient.get('patient_name') or 'Patient')} is with doctor")

    # Call Emergency patient
    if not is_future and not current_patient and emergency_waiting:
        emg_name = (emergency_waiting[0].get("patient_name") or "Emergency")
        if qa2.button(f"🚨 Call {emg_name}", type="primary", use_container_width=True, key="call_emg_top"):
            try:
                r = api.call_patient({"appointment_id": emergency_waiting[0]["appointment_id"]})
                st.session_state["dd_msg"] = r.get("message", f"🚨 {emg_name} called in!")
                st.rerun()
            except Exception as e:
                st.session_state["dd_msg"] = f"❌ {e}"
                st.rerun()
    elif not is_future and emergency_waiting and current_patient:
        qa2.warning(f"🚨 {len(emergency_waiting)} emergency waiting")

    # Mark no-shows (for past/today when booked patients remain)
    if not_arrived and not is_future:
        if qa3.button("⚠️ Mark Unarrived No-Show", use_container_width=True, key="bulk_noshow"):
            try:
                r = api.mark_no_shows({"session_id": session_id})
                st.session_state["dd_msg"] = r.get("message", "⚠️ No-shows marked.")
                st.rerun()
            except Exception as e:
                st.session_state["dd_msg"] = f"❌ {e}"
                st.rerun()

    # Add patient — separate section below patient list
    if not is_past:
        if qa4.button("➕ Add Patient", use_container_width=True, key="add_patient_toggle"):
            st.session_state["show_add_patient"] = not st.session_state.get("show_add_patient", False)

    st.divider()

    # ══════════════════════════════════════════════════
    # PATIENT LIST — every patient, click to expand
    # ══════════════════════════════════════════════════

    if not all_patients:
        st.info("No patients for this session yet.")

    # Helper: slot time string
    def _slot_time_str(entry):
        """Get slot time as HH:MM. Falls back to calculating from session start + slot number."""
        # Emergency patients (slot_number=0) have no scheduled time
        if entry.get("is_emergency") or entry.get("slot_number", 1) == 0:
            return "🚨 Emergency"
        t = entry.get("original_slot_time", "")
        if t:
            return str(t)[:5]
        # Fallback: calculate from session start time + slot * duration
        try:
            if session_start:
                hh, mm = int(session_start[:2]), int(session_start[3:5])
                slot_n = entry.get("slot_number", 1)
                total_min = hh * 60 + mm + (slot_n - 1) * default_dur
                return f"{total_min // 60:02d}:{total_min % 60:02d}"
        except Exception:
            pass
        return "—"

    # Helper: is a booked slot in the past?
    # If the session is still active, slot time being past does NOT block actions.
    # Doctor controls when session ends — nurse can check in patients anytime while active.
    def _slot_past(entry):
        # Active session → never treat slots as past (doctor is still working)
        if nurse_sess_status == "active" and is_today:
            return False
        if not is_today:
            return is_past
        try:
            slot_t = entry.get("original_slot_time", "")
            if slot_t:
                hh, mm = int(str(slot_t)[:2]), int(str(slot_t)[3:5])
                slot_end = hh * 60 + mm + (entry.get("duration_minutes") or default_dur)
                now_min = datetime.now().hour * 60 + datetime.now().minute
                return now_min > slot_end
            return False
        except Exception:
            return False

    # ── Render each patient ──
    # Sort: status group first, then within checked_in: emergency first, then priority (CRITICAL>HIGH>NORMAL), then visual_priority desc
    status_order = {"in_progress": 0, "checked_in": 1, "booked": 2, "completed": 3, "no_show": 4, "cancelled": 5}
    _prio_order = {"CRITICAL": 0, "HIGH": 1, "NORMAL": 2}
    sorted_patients = sorted(all_patients, key=lambda e: (
        status_order.get(e["status"], 9),
        0 if e.get("is_emergency") else 1,
        _prio_order.get(e.get("priority_tier", "NORMAL"), 2),
        -(e.get("visual_priority", 5)),
        e.get("slot_number", 0),
    ))

    for entry in sorted_patients:
        status = entry["status"]
        appt_id = entry["appointment_id"]
        name = entry.get("patient_name") or "Patient"
        slot = entry.get("slot_number", "?")
        slot_t = _slot_time_str(entry)
        priority = entry.get("priority_tier", "NORMAL")
        urgency = entry.get("visual_priority", 5)
        emg = " 🚨" if entry.get("is_emergency") else ""
        dur_min = entry.get("duration_minutes") or default_dur

        # Status config
        cfg = {
            "booked":      ("📅", "#3b82f6", "Booked"),
            "checked_in":  ("✅", "#f59e0b", "Waiting"),
            "in_progress": ("🔄", "#8b5cf6", "With Doctor"),
            "completed":   ("✔️", "#22c55e", "Completed"),
            "no_show":     ("⚠️", "#ef4444", "No-Show"),
            "cancelled":   ("❌", "#9ca3af", "Cancelled"),
        }
        icon, color, label = cfg.get(status, ("•", "#666", status))

        # Age/Gender string
        age_g = ""
        if entry.get("patient_age"):
            age_g = f"{entry['patient_age']}y"
        if entry.get("patient_gender"):
            age_g += f"/{entry['patient_gender'][:1].upper()}"

        # Wait time for checked-in patients
        # Normal patients: how long PAST their scheduled slot time (now - slot_time)
        # Emergency patients: time since check-in (now - checked_in_at)
        wait_str = ""
        if status == "checked_in":
            try:
                now_local = datetime.now()
                now_min = now_local.hour * 60 + now_local.minute

                slot_t_raw = entry.get("original_slot_time", "")
                if slot_t_raw and not entry.get("is_emergency"):
                    # Wait = now - scheduled slot time
                    s_hh, s_mm = int(str(slot_t_raw)[:2]), int(str(slot_t_raw)[3:5])
                    slot_min = s_hh * 60 + s_mm
                    wait_min = max(now_min - slot_min, 0)
                else:
                    # Emergency / no slot — time since check-in (local time)
                    ci_at = entry.get("checked_in_at")
                    if ci_at:
                        ci_str = str(ci_at)
                        # Strip timezone suffix if present — we stored local time
                        ci_time = datetime.fromisoformat(ci_str.replace("Z", "").split("+")[0])
                        wait_min = max(int((now_local - ci_time).total_seconds() / 60), 0)
                    else:
                        wait_min = 0
                wait_str = f"  •  ⏳ {wait_min}m"
            except Exception:
                pass

        # ── Step tracker (4-step visual flow) ──
        steps_data = [
            ("booked", "Booked"),
            ("checked_in", "Checked In"),
            ("in_progress", "With Doctor"),
            ("completed", "Done"),
        ]
        step_idx_map = {"booked": 0, "checked_in": 1, "in_progress": 2, "completed": 3, "no_show": -1, "cancelled": -2}
        cur_step = step_idx_map.get(status, -1)
        step_html = '<div style="display:flex;align-items:center;gap:0;margin:8px 0 12px 0">'
        for si, (s_key, s_label) in enumerate(steps_data):
            if cur_step < 0:
                bg_c, txt_c, brd = "#f3f4f6", "#9ca3af", "#e5e7eb"
                dot = "✕" if si == 0 else "○"
            elif si < cur_step:
                bg_c, txt_c, brd = "#dcfce7", "#16a34a", "#86efac"
                dot = "✓"
            elif si == cur_step:
                bg_c, txt_c, brd = color + "20", color, color
                dot = "●"
            else:
                bg_c, txt_c, brd = "#f9fafb", "#d1d5db", "#e5e7eb"
                dot = "○"
            step_html += (
                f'<div style="display:flex;flex-direction:column;align-items:center;min-width:70px">'
                f'<div style="width:28px;height:28px;border-radius:50%;background:{bg_c};border:2px solid {brd};'
                f'display:flex;align-items:center;justify-content:center;font-size:14px;color:{txt_c};font-weight:600">{dot}</div>'
                f'<span style="font-size:0.7em;color:{txt_c};margin-top:2px">{s_label}</span></div>'
            )
            if si < len(steps_data) - 1:
                line_c = "#86efac" if (cur_step >= 0 and si < cur_step) else "#e5e7eb"
                step_html += f'<div style="flex:1;height:2px;background:{line_c};margin:0 2px;align-self:flex-start;margin-top:14px"></div>'
        step_html += '</div>'

        # ── Expander header — time-first, slot secondary ──
        _slot_display = "🚨 Emergency" if int(slot) == 0 else f"{slot_t} (Slot {slot})"
        header = f"{icon} **{name}**{emg}  —  {_slot_display}  •  {label}{wait_str}"

        with st.expander(header, expanded=(status == "in_progress")):
            # Step tracker
            st.markdown(step_html, unsafe_allow_html=True)

            # ── Appointment Info (date, time, year) ──
            appt_date_display = s_date.strftime("%B %d, %Y") if s_date else session_date_str
            appt_day = s_date.strftime("%A") if s_date else ""
            st.markdown(
                f'<div style="background:#1e3a5f;border:1px solid #2d5a8e;border-radius:8px;padding:10px 14px;margin-bottom:10px">'
                f'<div style="display:flex;flex-wrap:wrap;gap:16px;font-size:0.9em;color:#e2e8f0">'
                f'<span>📆 <strong style="color:#ffffff">{appt_day}, {appt_date_display}</strong></span>'
                f'<span>🕐 <strong style="color:#ffffff">{slot_t}</strong> ({dur_min} min)</span>'
                f'<span>🩺 <strong style="color:#ffffff">{doctor_name}</strong></span>'
                f'<span>🎫 {"<strong style=color:#ffffff>Emergency</strong>" if int(slot) == 0 else f"Slot <strong style=color:#ffffff>#{slot}</strong>"}</span>'
                f'</div></div>',
                unsafe_allow_html=True,
            )

            # ── Patient details (two columns) ──
            d1, d2 = st.columns(2)
            with d1:
                st.markdown(
                    '<div style="background:#f8fafc;border-radius:8px;padding:10px 14px;border:1px solid #e2e8f0">',
                    unsafe_allow_html=True,
                )
                st.markdown("**Patient Info**")
                st.write(f"Name: **{name}**")
                if age_g:
                    st.write(f"Age/Gender: **{age_g}**")
                if entry.get("patient_blood_group"):
                    st.write(f"Blood Group: 🩸 **{entry['patient_blood_group']}**")
                risk = entry.get("patient_risk_score", 0) or 0
                risk_dot = "🟢" if risk < 5 else "🟡" if risk < 15 else "🔴"
                st.write(f"Risk Score: {risk_dot} **{risk:.0f}**")
                if entry.get("patient_abha_id"):
                    st.write(f"ABHA: {entry['patient_abha_id']}")
                st.markdown('</div>', unsafe_allow_html=True)
            with d2:
                st.markdown(
                    '<div style="background:#f8fafc;border-radius:8px;padding:10px 14px;border:1px solid #e2e8f0">',
                    unsafe_allow_html=True,
                )
                st.markdown("**Contact & Emergency**")
                st.write(f"📞 {entry.get('patient_phone') or '—'}")
                st.write(f"📍 {entry.get('patient_address') or '—'}")
                emg_name = entry.get("patient_emergency_contact")
                emg_phone = entry.get("patient_emergency_phone")
                if emg_name:
                    st.write(f"🚨 {emg_name} ({emg_phone or '—'})")
                else:
                    st.write("🚨 Emergency contact: —")
                st.markdown('</div>', unsafe_allow_html=True)

            # ── Priority / Urgency / Duration row ──
            _pill = "background:#e2e8f0;border-radius:16px;padding:4px 12px;font-size:0.85em;color:#1e293b"
            _emg_pill = "background:#fee2e2;border-radius:16px;padding:4px 12px;font-size:0.85em;color:#991b1b"
            _prio_pill = _emg_pill if priority == "CRITICAL" else ("background:#fff7ed;border-radius:16px;padding:4px 12px;font-size:0.85em;color:#9a3412" if priority == "HIGH" else _pill)
            st.markdown(
                f'<div style="display:flex;gap:12px;margin:8px 0;flex-wrap:wrap">'
                f'<div style="{_prio_pill}">Priority: <strong>{priority}</strong></div>'
                + (f'<div style="{_emg_pill}">🚨 <strong>EMERGENCY</strong></div>' if entry.get("is_emergency") else '')
                + f'<div style="{_pill}">Urgency: <strong>{urgency}/10</strong></div>'
                f'<div style="{_pill}">Duration: <strong>{dur_min}m</strong></div>'
                f'<div style="{_pill}">Queue Pos: <strong>{entry.get("slot_position", "—")}</strong></div>'
                f'</div>',
                unsafe_allow_html=True,
            )

            if entry.get("notes"):
                st.caption(f"📝 Notes: {entry['notes']}")

            # ══════════════════════════════════════
            # ACTIONS — time-aware, status-aware
            # Uses session_state action flags so buttons survive reruns
            # ══════════════════════════════════════

            action_key = f"action_{appt_id}"

            # Process any pending action from previous click
            pending = st.session_state.get(action_key)
            if pending:
                st.session_state.pop(action_key, None)
                try:
                    _dd_msg = ""
                    if pending == "checkin":
                        vp_val = st.session_state.get(f"vp_{appt_id}", 5)
                        dur_val = st.session_state.get(f"dur_{appt_id}", default_dur)
                        ci_prio_val = st.session_state.get(f"ci_prio_{appt_id}", "NORMAL")
                        ci_emg_val = st.session_state.get(f"ci_emg_{appt_id}", False)
                        payload = {
                            "appointment_id": appt_id,
                            "visual_priority": vp_val,
                            "priority_tier": ci_prio_val,
                            "is_emergency": ci_emg_val,
                        }
                        if dur_val != default_dur:
                            payload["duration_minutes"] = dur_val
                        r = api.checkin_patient(payload)
                        _dd_msg = f"✅ {name} checked in — #{r['queue_position']}"
                    elif pending == "cancel":
                        r = api.staff_cancel_appointment({"appointment_id": appt_id, "reason": "Cancelled by nurse"})
                        _dd_msg = f"✖ {name} cancelled."
                    elif pending == "noshow":
                        r = api.mark_no_shows({"session_id": session_id})
                        _dd_msg = f"⚠️ No-show recorded."
                    elif pending == "call":
                        r = api.call_next({"session_id": session_id})
                        _dd_msg = r.get("message", f"✅ Calling next patient")
                    elif pending == "undo_checkin":
                        r = api.undo_checkin({"appointment_id": appt_id})
                        _dd_msg = f"↩ {name} moved back to booked."
                    elif pending == "complete":
                        notes_val = st.session_state.get(f"notes_{appt_id}", "")
                        r = api.complete_appointment({"appointment_id": appt_id, "notes": notes_val})
                        _dd_msg = r.get("message", f"✅ {name} completed.")
                    elif pending == "complete_retro":
                        r = api.call_next({"session_id": session_id})
                        r2 = api.complete_appointment({"appointment_id": appt_id, "notes": "Completed retroactively by nurse"})
                        _dd_msg = f"✔️ {name} marked as completed."
                    elif pending == "back_to_queue":
                        r = api.undo_send({"session_id": session_id})
                        _dd_msg = f"↩ {name} sent back to waiting."
                    elif pending == "undo_complete":
                        r = api.undo_complete({"appointment_id": appt_id})
                        _dd_msg = f"↩ {name} moved back to with doctor."
                    elif pending == "undo_noshow":
                        r = api.undo_noshow({"appointment_id": appt_id})
                        _dd_msg = f"↩ {name} restored to booked."
                    elif pending == "remove_emergency":
                        # Slot 0 entries only exist because of emergency — cancel them entirely
                        _slot = entry.get("slot_number", 0)
                        if _slot == 0:
                            r = api.staff_cancel_appointment({"appointment_id": appt_id,
                                                               "reason": "Emergency removed — entry cancelled"})
                            _dd_msg = f"✅ {name} emergency entry cancelled."
                        else:
                            r = api.escalate_priority({"appointment_id": appt_id, "is_emergency": False,
                                                        "reason": "Emergency flag removed by staff"})
                            _dd_msg = f"✅ {name} removed from emergency status."
                    elif pending == "set_emergency":
                        r = api.escalate_priority({"appointment_id": appt_id, "is_emergency": True,
                                                    "priority_tier": "CRITICAL",
                                                    "reason": "Marked emergency by staff"})
                        _dd_msg = f"🚨 {name} marked as emergency."
                    if _dd_msg:
                        st.session_state["dd_msg"] = _dd_msg
                    import time as _t; _t.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    st.session_state["dd_msg"] = f"❌ Action failed: {e}"
                    st.rerun()

            # ── BOOKED ──
            if status == "booked":
                if is_future:
                    st.info("🕐 Future appointment — check-in available on session date.")
                    bc1, bc2 = st.columns(2)
                    if bc1.button("✖ Cancel Booking", key=f"btn_cx_{appt_id}", use_container_width=True):
                        st.session_state[action_key] = "cancel"
                        st.rerun()
                    if bc2.button("🔀 Reassign", key=f"btn_ra_{appt_id}", use_container_width=True):
                        st.session_state[f"reassign_{appt_id}"] = True
                        st.rerun()

                elif is_past or _slot_past(entry):
                    st.markdown(
                        '<div style="background:#fef2f2;border-left:3px solid #ef4444;padding:6px 12px;'
                        'border-radius:4px;font-size:0.85em;color:#991b1b;margin-bottom:8px">'
                        '⏰ Slot time has passed — patient did not arrive.</div>',
                        unsafe_allow_html=True,
                    )
                    bc1, bc2 = st.columns(2)
                    if bc1.button("⚠️ Mark No-Show", key=f"btn_ns_{appt_id}", use_container_width=True):
                        st.session_state[action_key] = "noshow"
                        st.rerun()
                    if bc2.button("🔀 Reassign", key=f"btn_ra_{appt_id}", use_container_width=True):
                        st.session_state[f"reassign_{appt_id}"] = True
                        st.rerun()

                else:
                    # Today, slot active — full check-in with priority assessment
                    ci_r1, ci_r2 = st.columns(2)
                    ci_priority = ci_r1.selectbox(
                        "Priority", ["NORMAL", "HIGH", "CRITICAL"],
                        key=f"ci_prio_{appt_id}",
                    )
                    ci_emergency = ci_r2.checkbox(
                        "🚨 Emergency", key=f"ci_emg_{appt_id}",
                        help="Mark if patient needs immediate attention",
                    )
                    ci_r3, ci_r4 = st.columns(2)
                    vp = ci_r3.slider("Urgency (1-10)", 1, 10,
                                      10 if ci_emergency else (8 if ci_priority == "CRITICAL" else 5),
                                      key=f"vp_{appt_id}")
                    dur = ci_r4.number_input("Duration (min)", 5, 120, default_dur, key=f"dur_{appt_id}")
                    bc1, bc2, bc3 = st.columns(3)
                    if bc1.button("✅ Check In", key=f"btn_ci_{appt_id}", type="primary", use_container_width=True):
                        st.session_state[action_key] = "checkin"
                        st.rerun()
                    if bc2.button("✖ Cancel", key=f"btn_cx_{appt_id}", use_container_width=True):
                        st.session_state[action_key] = "cancel"
                        st.rerun()
                    if bc3.button("🔀 Reassign", key=f"btn_ra_{appt_id}", use_container_width=True):
                        st.session_state[f"reassign_{appt_id}"] = True
                        st.rerun()

            # ── CHECKED IN (waiting) ──
            elif status == "checked_in":
                if is_today:
                    # ── Priority update (nurse can reassess while patient waits) ──
                    with st.popover("⚡ Update Priority", use_container_width=False):
                        cur_prio = entry.get("priority_tier", "NORMAL")
                        cur_emg = entry.get("is_emergency", False)
                        up_prio = st.selectbox("Priority Tier", ["NORMAL", "HIGH", "CRITICAL"],
                                               index=["NORMAL", "HIGH", "CRITICAL"].index(cur_prio) if cur_prio in ["NORMAL", "HIGH", "CRITICAL"] else 0,
                                               key=f"up_prio_{appt_id}")
                        up_emg = st.checkbox("🚨 Emergency", value=cur_emg, key=f"up_emg_{appt_id}")
                        up_urg = st.slider("Urgency (1-10)", 1, 10, entry.get("visual_priority", 5), key=f"up_urg_{appt_id}")
                        up_reason = st.text_input("Reason", key=f"up_reason_{appt_id}", placeholder="e.g. condition worsened")
                        if st.button("Save", key=f"up_save_{appt_id}", type="primary", use_container_width=True):
                            if not up_reason or len(up_reason.strip()) < 3:
                                st.error("Reason required (3+ chars)")
                            else:
                                try:
                                    api.escalate_priority({
                                        "appointment_id": appt_id,
                                        "priority_tier": up_prio,
                                        "is_emergency": up_emg,
                                        "visual_priority": up_urg,
                                        "reason": up_reason.strip(),
                                    })
                                    st.session_state["dd_msg"] = f"✅ Priority updated for {name}"
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Failed: {e}")

                    _is_emg = entry.get("is_emergency", False)
                    _is_slot0 = entry.get("slot_number", 0) == 0
                    bc1, bc2, bc3, bc4 = st.columns(4)
                    # Call to Doctor
                    if not current_patient:
                        if bc1.button("🔔 Call", key=f"btn_call_{appt_id}", type="primary", use_container_width=True):
                            st.session_state[action_key] = "call"
                            st.rerun()
                    else:
                        bc1.info("🔄 Doctor busy")
                    # Emergency toggle — show Remove if emergency, Set if not
                    if _is_emg:
                        if bc2.button("🚫 Remove Emergency", key=f"btn_remg_{appt_id}", use_container_width=True):
                            st.session_state[action_key] = "remove_emergency"
                            st.rerun()
                    else:
                        if bc2.button("🚨 Set Emergency", key=f"btn_semg_{appt_id}", use_container_width=True):
                            st.session_state[action_key] = "set_emergency"
                            st.rerun()
                    # Cancel
                    if bc3.button("✖ Cancel", key=f"btn_cx_{appt_id}", use_container_width=True):
                        st.session_state[action_key] = "cancel"
                        st.rerun()
                    # Undo check-in (only for regular slots, not slot 0 emergency entries)
                    if not _is_slot0:
                        if bc4.button("↩ Undo", key=f"btn_uci_{appt_id}", use_container_width=True):
                            st.session_state[action_key] = "undo_checkin"
                            st.rerun()
                    else:
                        if bc4.button("🔀 Reassign", key=f"btn_ra_{appt_id}", use_container_width=True):
                            st.session_state[f"reassign_{appt_id}"] = True
                            st.rerun()

                elif is_past:
                    st.markdown(
                        '<div style="background:#fef9c3;border-left:3px solid #eab308;padding:6px 12px;'
                        'border-radius:4px;font-size:0.85em;color:#854d0e;margin-bottom:8px">'
                        '⏰ Past session — patient attended. Mark as completed if doctor saw them.</div>',
                        unsafe_allow_html=True,
                    )
                    bc1, bc2 = st.columns(2)
                    if bc1.button("✔️ Mark Completed", key=f"btn_comp_r_{appt_id}", type="primary", use_container_width=True):
                        st.session_state[action_key] = "complete_retro"
                        st.rerun()
                    if bc2.button("⚠️ Mark No-Show", key=f"btn_ns_{appt_id}", use_container_width=True):
                        st.session_state[action_key] = "noshow"
                        st.rerun()

            # ── IN PROGRESS (with doctor) ──
            elif status == "in_progress":
                if not is_future:
                    notes = st.text_input("Visit notes", key=f"notes_{appt_id}", placeholder="Optional notes…")
                    bc1, bc2, bc3 = st.columns(3)
                    if bc1.button("✅ Complete", key=f"btn_comp_{appt_id}", type="primary", use_container_width=True):
                        st.session_state[action_key] = "complete"
                        st.rerun()
                    if bc2.button("↩ Back to Queue", key=f"btn_sb_{appt_id}", use_container_width=True):
                        st.session_state[action_key] = "back_to_queue"
                        st.rerun()
                    if bc3.button("🔀 Reassign", key=f"btn_ra_{appt_id}", use_container_width=True):
                        st.session_state[f"reassign_{appt_id}"] = True
                        st.rerun()
                else:
                    st.info("🕐 Future session — actions available on session date.")

            # ── COMPLETED ──
            elif status == "completed":
                completed_at = entry.get("completed_at", "")
                if completed_at:
                    st.markdown(
                        f'<div style="background:#f0fdf4;border-left:3px solid #22c55e;padding:6px 12px;'
                        f'border-radius:4px;font-size:0.85em;color:#166534;margin-bottom:8px">'
                        f'✔️ Completed at: {str(completed_at)[:16]}</div>',
                        unsafe_allow_html=True,
                    )
                if is_today:
                    if st.button("↩ Undo Complete", key=f"btn_uc_{appt_id}", use_container_width=True):
                        st.session_state[action_key] = "undo_complete"
                        st.rerun()
                else:
                    st.caption("✔️ Final — no further actions.")

            # ── NO-SHOW ──
            elif status == "no_show":
                if is_today:
                    if st.button("↩ Restore (Patient Arrived)", key=f"btn_uns_{appt_id}", use_container_width=True):
                        st.session_state[action_key] = "undo_noshow"
                        st.rerun()
                elif is_past:
                    st.caption("⚠️ Marked as no-show. Session is past — no changes possible.")
                else:
                    st.caption("No actions for future sessions.")

            # ── Reassign form ──
            if st.session_state.get(f"reassign_{appt_id}"):
                with st.form(f"reassign_form_{appt_id}"):
                    st.markdown(f"**🔀 Reassign {name} to another doctor**")
                    try:
                        all_docs = api.list_doctors()
                    except Exception:
                        all_docs = []
                    other_docs = {
                        f"{d['full_name']} — {d['specialization']}": d["doctor_id"]
                        for d in all_docs
                    }
                    if not other_docs:
                        st.warning("No doctors available.")
                        st.form_submit_button("Close", disabled=True)
                    else:
                        rc1, rc2 = st.columns(2)
                        sel_doc_label = rc1.selectbox("Doctor", list(other_docs.keys()), key=f"re_doc_{appt_id}")
                        sel_doc_id = other_docs.get(sel_doc_label, "")
                        try:
                            t_sessions = api.get_doctor_sessions(sel_doc_id, str(s_date), str(s_date)) if sel_doc_id else []
                        except Exception:
                            t_sessions = []
                        avail = {
                            f"{s['start_time'][:5]}–{s['end_time'][:5]} ({s['available_capacity']} avail)": s
                            for s in t_sessions if s.get("available_capacity", 0) > 0
                        }
                        if not avail:
                            st.warning("No available sessions for this doctor.")
                            st.form_submit_button("Close", disabled=True)
                        else:
                            sel_sess_label = rc2.selectbox("Session", list(avail.keys()), key=f"re_sess_{appt_id}")
                            sel_sess = avail.get(sel_sess_label, {})
                            t_slot = st.number_input("Slot", 1, sel_sess.get("total_slots", 20), 1, key=f"re_slot_{appt_id}")
                            fc1, fc2 = st.columns(2)
                            if fc1.form_submit_button("✅ Confirm Reassign", type="primary"):
                                try:
                                    r = api.reassign_appointment({
                                        "appointment_id": appt_id,
                                        "target_session_id": sel_sess["session_id"],
                                        "target_slot_number": t_slot,
                                    })
                                    st.session_state["dd_msg"] = r.get("message", f"✅ {name} reassigned.")
                                    st.session_state.pop(f"reassign_{appt_id}", None)
                                    st.rerun()
                                except Exception as e:
                                    st.session_state["dd_msg"] = f"❌ Reassign failed: {e}"
                                    st.rerun()
                            if fc2.form_submit_button("Cancel"):
                                st.session_state.pop(f"reassign_{appt_id}", None)
                                st.rerun()

    # ── Delay & Overtime Management ──────────────────────────
    if is_today or is_future:
        with st.expander("⏱️ Delay & Overtime Management", expanded=False):
            dc1, dc2 = st.columns(2)
            with dc1:
                st.subheader("Doctor Arrival")
                st.caption("Press when doctor arrives. If late, delay is auto-calculated.")
                if st.button("🏥 Doctor is Here", type="primary", use_container_width=True, key="staff_doc_checkin"):
                    try:
                        r = api.doctor_checkin({"session_id": session_id})
                        st.success(r["message"])
                    except Exception as e:
                        st.error(f"{e}")

                st.divider()
                st.subheader("Manual Delay")
                st.caption("If running behind, update so patients see accurate estimated times.")
                with st.form("staff_delay_form"):
                    delay = st.number_input("Minutes behind schedule", min_value=0, max_value=120, value=q.get("delay_minutes", 0))
                    reason = st.text_input("Reason (optional)")
                    if st.form_submit_button("Update Delay"):
                        try:
                            r = api.update_delay({"session_id": session_id, "delay_minutes": delay, "reason": reason})
                            st.success(r["message"])
                        except Exception as e:
                            st.error(f"{e}")

            with dc2:
                # Only show overtime/extend for afternoon sessions (start >= 14:00)
                _staff_is_afternoon = False
                try:
                    _staff_is_afternoon = int(str(session_start)[:2]) >= 14
                except Exception:
                    pass

                if _staff_is_afternoon:
                    st.subheader("Overtime Check")
                    st.caption("If running late, check who can still be seen if doctor stays extra.")
                    with st.form("staff_ot_form"):
                        ot = st.number_input("Extra minutes available", min_value=0, max_value=60, value=15)
                        if st.form_submit_button("Check"):
                            try:
                                r = api.overtime_window({"session_id": session_id, "overtime_minutes": ot})
                                st.info(r["message"])
                                for p in r.get("patients_can_be_seen", []):
                                    st.write(f"  ✅ {(p.get('patient_name') or '?')} — can be seen")
                                for p in r.get("patients_cannot_be_seen", []):
                                    st.write(f"  ❌ {(p.get('patient_name') or '?')} — needs reschedule")
                            except Exception as e:
                                st.error(f"{e}")

                    st.divider()
                    st.subheader("Extend Session")
                    st.caption("Extend the session end time to accommodate more patients.")
                    with st.form("staff_extend_form"):
                        new_end = st.time_input("New end time")
                        note = st.text_input("Reason")
                        if st.form_submit_button("Extend"):
                            try:
                                r = api.extend_session({"session_id": session_id, "new_end_time": str(new_end), "note": note})
                                st.toast(r.get('message', 'Session extended!'), icon="✅")
                                st.rerun()
                            except Exception as e:
                                st.error(f"{e}")
                else:
                    st.info("☀️ **Morning session** — Extend/Overtime not available. "
                            "Pending patients will automatically carry over to the afternoon session.")

    # ══════════════════════════════════════════════════════
    # ADD PATIENT — full booking form (Department → Doctor → Time)
    # ══════════════════════════════════════════════════════
    if st.session_state.get("show_add_patient") and not is_past:
        st.divider()
        st.markdown("### ➕ Add Patient")

        add_mode = st.radio(
            "Booking type",
            ["📋 Regular", "🚨 Emergency (can overbook)"],
            key="add_mode",
            horizontal=True,
        )
        is_emergency_book = "Emergency" in add_mode

        add_tab_new, add_tab_existing = st.tabs(["🆕 New Patient (Walk-in)", "🔍 Existing Patient"])

        # ── Helper: check if a session has ended ──
        def _session_has_ended(s_end_time, s_date_str=None):
            """Check if session has ended (today and past end time)."""
            try:
                s_d = _date_type.fromisoformat(s_date_str) if s_date_str else None
                if s_d and s_d != _date_type.today():
                    return s_d < _date_type.today()
                eh, em = int(str(s_end_time)[:2]), int(str(s_end_time)[3:5])
                return datetime.now().hour * 60 + datetime.now().minute >= eh * 60 + em
            except Exception:
                return False

        # ── Helper: build time slots for any session ──
        def _build_time_slots(s_start, s_end, s_total_slots, s_dur, s_max_per_slot,
                              s_date_str=None, s_slot_counts=None, emergency=False):
            """Build time slot options, filtering past/out-of-range. Returns (time_options, available_options)."""
            opts = []
            s_end_min = None
            try:
                eh, em = int(str(s_end)[:2]), int(str(s_end)[3:5])
                s_end_min = eh * 60 + em
            except Exception:
                pass

            s_is_today = False
            try:
                s_is_today = _date_type.fromisoformat(str(s_date_str)) == _date_type.today()
            except Exception:
                pass

            now_min = datetime.now().hour * 60 + datetime.now().minute
            counts = s_slot_counts or {}

            for sn in range(1, s_total_slots + 1):
                try:
                    sh, sm = int(str(s_start)[:2]), int(str(s_start)[3:5])
                    total_min = sh * 60 + sm + (sn - 1) * s_dur
                except Exception:
                    opts.append({"label": f"Slot {sn}", "slot": sn, "full": False})
                    continue

                # Skip slots past session end
                if s_end_min and total_min >= s_end_min:
                    continue
                # Skip past slots (today only)
                if s_is_today and now_min > (total_min + s_dur):
                    continue

                t_lbl = f"{total_min // 60:02d}:{total_min % 60:02d}"
                count = counts.get(sn, 0)

                overbook_limit = s_max_per_slot + 1  # Allow at most 1 extra (emergency)
                if count >= s_max_per_slot and not emergency:
                    opts.append({"label": f"❌ {t_lbl} — FULL ({count}/{s_max_per_slot})", "slot": sn, "full": True})
                elif count >= overbook_limit and emergency:
                    opts.append({"label": f"❌ {t_lbl} — MAX REACHED ({count}/{s_max_per_slot}+1)", "slot": sn, "full": True})
                elif count >= s_max_per_slot and emergency:
                    opts.append({"label": f"🚨 {t_lbl} — OVERBOOK ({count}/{s_max_per_slot})", "slot": sn, "full": False})
                elif count > 0:
                    opts.append({"label": f"🟡 {t_lbl} — {count}/{s_max_per_slot} booked", "slot": sn, "full": False})
                else:
                    opts.append({"label": f"🟢 {t_lbl} — Available", "slot": sn, "full": False})

            avail = [o for o in opts if not o["full"]]
            return opts, avail

        # ── Check current session status ──
        current_session_ended = _session_has_ended(session_end, session_date_str)

        # ── Build slot counts for current session ──
        slot_counts = {}
        for e in all_entries:
            sn = e.get("slot_number", 0)
            if e.get("status") in ("booked", "checked_in", "in_progress", "completed"):
                slot_counts[sn] = slot_counts.get(sn, 0) + 1
        if current_patient:
            csn = current_patient.get("slot_number", 0)
            slot_counts[csn] = slot_counts.get(csn, 0) + 1

        # ── Session picker ──
        # If current session is still active, offer it as default
        # Otherwise, go straight to session selection
        if current_session_ended:
            st.info("⏰ This session has ended. Pick another session below to book a patient.")
            book_where = "pick"
        else:
            book_where_opts = ["📌 This session (current)", "🔄 Pick a different session"]
            book_where_choice = st.radio("Book where?", book_where_opts, key="book_where", horizontal=True)
            book_where = "current" if "current" in book_where_choice else "pick"

        target_session_id = None
        target_doc_name = doctor_name
        time_options = []
        available_options = []

        if book_where == "current":
            # ── Use current session ──
            target_session_id = session_id
            total_slots = q.get("total_slots", 20)
            slot_dur = q.get("slot_duration_minutes", 15)
            max_per_slot = q.get("max_patients_per_slot", 2)

            time_options, available_options = _build_time_slots(
                session_start, session_end, total_slots, slot_dur, max_per_slot,
                s_date_str=session_date_str, s_slot_counts=slot_counts,
                emergency=is_emergency_book,
            )
            if not time_options:
                st.warning("⏰ No upcoming time slots remaining for this session.")
            elif not available_options:
                st.warning("All time slots are full. Switch to **Emergency** mode to overbook.")

        else:
            # ── Pick any session (Department → Doctor → Session → Time) ──
            try:
                bk_all_docs = api.list_doctors()
            except Exception:
                bk_all_docs = []
            bk_specs = sorted(set(d["specialization"] for d in bk_all_docs))
            bk_spec_opts = ["— Select Department —"] + bk_specs
            bk_spec = st.selectbox("🏥 Department", bk_spec_opts, key="bk_dept")

            if bk_spec != "— Select Department —":
                bk_filtered = [d for d in bk_all_docs if d["specialization"] == bk_spec]
                bk_doc_opts = ["— Select Doctor —"] + [
                    d['full_name'] if d['full_name'].lower().startswith("dr") else f"Dr. {d['full_name']}"
                    for d in bk_filtered
                ]
                bk_doc_choice = st.selectbox("🩺 Doctor", bk_doc_opts, key="bk_doc")
                if bk_doc_choice != "— Select Doctor —":
                    bk_chosen = bk_filtered[bk_doc_opts.index(bk_doc_choice) - 1]
                    target_doc_name = bk_chosen["full_name"]
                    try:
                        bk_sessions = api.get_doctor_sessions(bk_chosen["doctor_id"],
                                                               str(_date_type.today()), "")
                    except Exception:
                        bk_sessions = []
                    # Filter: active, not ended, has capacity (or emergency)
                    bk_active = [
                        s for s in bk_sessions
                        if s["status"] == "active"
                        and (s.get("available_capacity", 0) > 0 or is_emergency_book)
                        and not _session_has_ended(s.get("end_time", "23:59"), s.get("session_date"))
                    ]
                    if not bk_active:
                        st.warning("No upcoming sessions for this doctor. All sessions have ended or are full.")
                    else:
                        bk_sess_labels = [
                            f"{s['session_date']} • {s['start_time'][:5]}–{s['end_time'][:5]} ({s.get('available_capacity', 0)} avail)"
                            for s in bk_active
                        ]
                        bk_sess_idx = st.selectbox("🕐 Session", range(len(bk_sess_labels)),
                                                    format_func=lambda i: bk_sess_labels[i], key="bk_sess")
                        target_session_id = bk_active[bk_sess_idx]["session_id"]
                        bk_sess = bk_active[bk_sess_idx]
                        bk_total = bk_sess.get("total_slots", 20)
                        bk_dur = bk_sess.get("slot_duration_minutes", 15)
                        bk_start = bk_sess.get("start_time", "09:00")
                        bk_end = bk_sess.get("end_time", "17:00")
                        bk_max = bk_sess.get("max_patients_per_slot", 2)

                        # Get real slot counts for the target session via queue API
                        bk_slot_counts = {}
                        try:
                            bk_q = api.get_queue(target_session_id)
                            for be in bk_q.get("queue", []):
                                bsn = be.get("slot_number", 0)
                                if be.get("status") in ("booked", "checked_in", "in_progress", "completed"):
                                    bk_slot_counts[bsn] = bk_slot_counts.get(bsn, 0) + 1
                            bk_cp = bk_q.get("current_patient")
                            if bk_cp:
                                bcsn = bk_cp.get("slot_number", 0)
                                bk_slot_counts[bcsn] = bk_slot_counts.get(bcsn, 0) + 1
                        except Exception:
                            pass  # Fall back to 0 counts

                        time_options, available_options = _build_time_slots(
                            bk_start, bk_end, bk_total, bk_dur, bk_max,
                            s_date_str=bk_sess.get("session_date"),
                            s_slot_counts=bk_slot_counts,
                            emergency=is_emergency_book,
                        )
                        if not time_options:
                            st.warning("⏰ No upcoming time slots for this session.")
                        elif not available_options:
                            st.warning("All time slots are full. Switch to **Emergency** mode to overbook.")

        # Time picker
        if available_options:
            time_labels = [o["label"] for o in available_options]
            time_idx = st.selectbox("🕐 Select Time", range(len(time_labels)),
                                     format_func=lambda i: time_labels[i], key="bk_time")
            chosen_slot = available_options[time_idx]["slot"]
        else:
            chosen_slot = None

        # ── Tab 1: Register new patient + book ──
        with add_tab_new:
            with st.form("new_patient_form"):
                st.markdown("**Patient Details**")
                np1, np2 = st.columns(2)
                np_name = np1.text_input("Full Name *", key="np_name", placeholder="e.g. Amit Patel")
                np_phone = np2.text_input("Phone", key="np_phone", placeholder="e.g. 9876543210")

                np3, np4, np5 = st.columns(3)
                np_gender = np3.selectbox("Gender", ["male", "female", "other"], key="np_gender")
                np_dob = np4.date_input("Date of Birth", value=_date_type(1990, 1, 1), key="np_dob",
                                        min_value=_date_type(1920, 1, 1), max_value=_date_type.today())
                np_blood = np5.selectbox("Blood Group", ["", "A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"],
                                         key="np_blood")

                np6, np7 = st.columns(2)
                np_abha = np6.text_input("ABHA ID (optional)", key="np_abha", placeholder="14-digit UHID")
                np_address = np7.text_input("Address", key="np_address", placeholder="Full address")

                st.markdown("**Emergency Contact**")
                ec1, ec2 = st.columns(2)
                np_emg_name = ec1.text_input("Emergency Contact Name", key="np_emg_name")
                np_emg_phone = ec2.text_input("Emergency Contact Phone", key="np_emg_phone")

                if st.form_submit_button("✅ Register & Book", type="primary", use_container_width=True):
                    if not np_name or len(np_name.strip()) < 2:
                        st.error("Full name is required (at least 2 characters).")
                    elif chosen_slot is None or target_session_id is None:
                        st.error("Please select a time slot and session first.")
                    else:
                        try:
                            payload = {
                                "full_name": np_name.strip(),
                                "phone": np_phone.strip(),
                                "gender": np_gender,
                                "date_of_birth": str(np_dob),
                                "blood_group": np_blood,
                                "abha_id": np_abha.strip(),
                                "address": np_address.strip(),
                                "emergency_contact": np_emg_name.strip(),
                                "emergency_phone": np_emg_phone.strip(),
                                "session_id": target_session_id,
                                "slot_number": chosen_slot,
                            }
                            r = api.staff_register_book(payload)
                            st.success(f"✅ {np_name} registered and booked — {r['message']}")
                            st.session_state["show_add_patient"] = False
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed: {e}")

        # ── Tab 2: Search existing patient + book ──
        with add_tab_existing:
            p_search = st.text_input("🔍 Search by name or phone", key="add_p_search", placeholder="Type 2+ characters…")
            if p_search and len(p_search) >= 2:
                try:
                    found = api.search_patients(p_search)
                    if not found:
                        st.info("No patients found. Use the **New Patient** tab to register them.")
                    for fp in found[:5]:
                        fp_age = f"{fp['age']}y" if fp.get('age') else "—"
                        fp_gender = fp.get('gender', '—')
                        fp_phone = fp.get('phone', '—')
                        fp_bg = fp.get('blood_group', '')
                        with st.container(border=True):
                            fc1, fc2 = st.columns([5, 1])
                            fc1.markdown(
                                f"**{fp['full_name']}**  •  {fp_age}"
                                f"/{fp_gender[:1].upper() if fp_gender and fp_gender != '—' else '—'}"
                                f"  •  📞 {fp_phone}"
                                + (f"  •  🩸 {fp_bg}" if fp_bg else "")
                            )
                            can_book = chosen_slot is not None and target_session_id is not None
                            if fc2.button("📋 Book", key=f"sb_{fp['patient_id']}", type="primary",
                                          use_container_width=True, disabled=not can_book):
                                try:
                                    r = api.staff_book({
                                        "session_id": target_session_id,
                                        "patient_id": fp["patient_id"],
                                        "slot_number": chosen_slot,
                                    })
                                    st.success(f"✅ {fp['full_name']} booked — {r['message']}")
                                    st.session_state["show_add_patient"] = False
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Booking failed: {e}")
                            if not can_book:
                                fc2.caption("Select time")
                except Exception as e:
                    st.error(f"Search failed: {e}")

        if st.button("✖ Close", key="close_add_patient"):
            st.session_state["show_add_patient"] = False
            st.rerun()


# ════════════════════════════════════════════════════════════
# EMERGENCY BOOKING (nurse/admin)
# ════════════════════════════════════════════════════════════

def page_nurse_emergency():
    tc1, tc2 = st.columns([6, 1])
    tc1.title("🚨 Emergency Booking")
    if tc2.button("🔄 Refresh", key="refresh_nurse_emg", use_container_width=True):
        st.rerun()
    st.warning("Bypasses rate limits & risk scores. Only for real emergencies.")

    # Show success/error from previous action
    if st.session_state.get("emg_msg"):
        st.success(st.session_state.pop("emg_msg"))

    session_id = _smart_session_picker("emg_sp")
    if not session_id:
        return

    st.info("Emergency patients are added directly to the queue **without a time slot**. "
            "The doctor can call them at any time, bypassing the normal queue order.")

    # ── Show current emergency patients in this session with cancel option ──
    try:
        _emg_q = api.get_queue(session_id)
        _emg_entries = [e for e in _emg_q.get("queue", [])
                        if e.get("is_emergency") and e["status"] not in ("cancelled", "no_show", "completed")]
        if _emg_entries:
            st.markdown(f"### 🚨 Current Emergency Patients ({len(_emg_entries)})")
            for _ei, _ee in enumerate(_emg_entries):
                _ec1, _ec2, _ec3 = st.columns([4, 2, 1])
                _ee_name = _ee.get("patient_name") or "Patient"
                _ee_status = _ee.get("status", "")
                _ee_prio = _ee.get("priority_tier", "CRITICAL")
                _status_badge = {"checked_in": "⏳ Waiting", "in_progress": "🔄 With Doctor", "booked": "📅 Booked"}.get(_ee_status, _ee_status)
                _ec1.write(f"**{_ee_name}**  •  {_ee_prio}  •  {_status_badge}")
                _ec2.caption(f"Slot pos: {_ee.get('slot_position', '—')}")
                if _ee_status in ("checked_in", "booked"):
                    if _ec3.button("✖ Cancel", key=f"emg_cx_{_ei}", use_container_width=True):
                        try:
                            api.staff_cancel_appointment({"appointment_id": _ee["appointment_id"],
                                                          "reason": "Cancelled from emergency page"})
                            st.session_state["emg_msg"] = f"Cancelled emergency entry for {_ee_name}"
                            st.rerun()
                        except Exception as _ex:
                            st.error(f"Cancel failed: {_ex}")
            st.divider()
    except Exception:
        pass  # non-critical — don't block the booking form

    # Get patients from queue for easy pick
    try:
        q = api.get_queue(session_id)
        known = []
        seen = set()
        for e in q.get("queue", []):
            if e.get("patient_id") and e["patient_id"] not in seen:
                seen.add(e["patient_id"])
                known.append({"id": e["patient_id"], "label": e.get('patient_name') or e['patient_id'][:8]})
    except Exception:
        known = []

    mode = st.radio("Find patient", ["Search by name", "Pick from known patients", "Enter Patient ID", "New walk-in patient"], horizontal=True, key="emg_mode")
    patient_id = None
    _emg_new_walkin = False
    if mode == "Search by name":
        search_q = st.text_input("Search patient name or phone", key="emg_search")
        if search_q and len(search_q) >= 2:
            try:
                results = api.search_patients(search_q)
                if results:
                    sr_labels = [f"{r['full_name']} — {r.get('phone', '')}" for r in results]
                    sr_idx = st.selectbox("Select patient", range(len(sr_labels)),
                                           format_func=lambda i: sr_labels[i], key="emg_sr")
                    patient_id = results[sr_idx]["patient_id"]
                else:
                    st.info("No patients found. Use **New walk-in patient** to register.")
            except Exception:
                st.warning("Search failed.")
    elif mode == "Pick from known patients":
        if known:
            p_labels = [p["label"] for p in known]
            p_idx = st.selectbox("Patient", range(len(p_labels)), format_func=lambda i: p_labels[i])
            patient_id = known[p_idx]["id"]
        else:
            st.info("No patients in current session queue.")
    elif mode == "Enter Patient ID":
        patient_id = st.text_input("Patient ID")
    else:
        # New walk-in patient — quick register
        _emg_new_walkin = True
        st.caption("Quick-register a new patient for this emergency.")
        _emg_wc1, _emg_wc2 = st.columns(2)
        _emg_walk_name = _emg_wc1.text_input("Full Name *", key="emg_walk_name")
        _emg_walk_phone = _emg_wc2.text_input("Phone (optional)", key="emg_walk_phone")

    priority = st.selectbox("Priority Level", ["CRITICAL", "HIGH", "NORMAL"], key="emg_priority")
    reason = st.text_area("Emergency Reason (required)")

    # Prevent double-submit: track if we already submitted
    _emg_submitted_key = "emg_submitted"
    if st.button("⚡ Add Emergency Patient", type="primary", use_container_width=True,
                  disabled=st.session_state.get(_emg_submitted_key, False)):
        if _emg_new_walkin:
            if not _emg_walk_name or len(_emg_walk_name.strip()) < 2:
                st.error("Enter a name for the patient.")
            elif not reason or len(reason) < 5:
                st.error("Reason must be at least 5 characters.")
            else:
                st.session_state[_emg_submitted_key] = True
                try:
                    reg = api.quick_register_patient({"full_name": _emg_walk_name.strip(),
                                                       "phone": _emg_walk_phone.strip() if _emg_walk_phone else None})
                    patient_id = reg.get("patient_id")
                    if not patient_id:
                        st.error("Registration failed — no patient ID returned.")
                        st.session_state[_emg_submitted_key] = False
                    else:
                        r = api.emergency_book({"session_id": session_id,
                                                 "patient_id": patient_id,
                                                 "reason": reason,
                                                 "priority_tier": priority})
                        st.session_state["emg_msg"] = f"✅ Registered & added: {r['message']}"
                        st.session_state[_emg_submitted_key] = False
                        st.rerun()
                except Exception as e:
                    st.error(f"Failed: {e}")
                    st.session_state[_emg_submitted_key] = False
        elif not patient_id:
            st.error("Select a patient first.")
        elif not reason or len(reason) < 5:
            st.error("Reason must be at least 5 characters.")
        else:
            st.session_state[_emg_submitted_key] = True
            try:
                r = api.emergency_book({"session_id": session_id,
                                         "patient_id": patient_id,
                                         "reason": reason,
                                         "priority_tier": priority})
                st.session_state["emg_msg"] = f"✅ {r['message']}"
                st.session_state[_emg_submitted_key] = False
                st.rerun()
            except Exception as e:
                st.error(f"Failed: {e}")
                st.session_state[_emg_submitted_key] = False


# ════════════════════════════════════════════════════════════
# NURSE / ADMIN — PATIENT MANAGEMENT
# ════════════════════════════════════════════════════════════

def page_nurse_patients():
    """Nurse patient management — search, view details, book appointments, update profiles."""
    from datetime import date as _d

    tc1, tc2 = st.columns([6, 1])
    tc1.title("🏥 Patient Lookup")
    if tc2.button("🔄 Refresh", key="refresh_nurse_pat", use_container_width=True):
        st.rerun()

    if st.session_state.get("nurse_pat_msg"):
        st.success(st.session_state.pop("nurse_pat_msg"))

    # ── Filters ──
    fc1, fc2 = st.columns([3, 1])
    search = fc1.text_input("🔍 Search", key="nurse_pat_search", placeholder="Name, phone, or ABHA...")
    high_risk = fc2.checkbox("High risk only", key="nurse_pat_hr")

    try:
        patients = api.admin_list_patients(
            search=search if search and len(search) >= 2 else "",
            high_risk_only=high_risk,
        )
    except Exception as e:
        st.error(f"Failed: {e}"); return

    if not patients:
        st.info("No patients found."); return

    st.caption(f"Showing {len(patients)} patients")

    for p in patients:
        pid = str(p["patient_id"])
        try:
            risk = float(p.get("risk_score") or 0)
        except (ValueError, TypeError):
            risk = 0.0
        risk_dot = "🟢" if risk < 3 else "🟡" if risk < 7 else "🔴"
        total_appt = int(p.get("total_appointments") or 0)
        no_shows = int(p.get("no_shows") or 0)

        age_str = ""
        if p.get("date_of_birth") and p["date_of_birth"] != "None":
            try:
                dob = _d.fromisoformat(str(p["date_of_birth"])[:10])
                age_str = f"{(_d.today() - dob).days // 365}y"
            except Exception:
                pass
        gender_str = (p.get("gender") or "—")[:1].upper() if p.get("gender") and p["gender"] != "None" else "—"
        name = p.get("full_name", "—")

        header = (
            f"{risk_dot} **{name}**  •  {age_str}/{gender_str}  "
            f"•  📞 {p.get('phone') or '—'}  •  🩸 {p.get('blood_group') or '—'}  "
            f"•  Visits: {total_appt}"
        )

        with st.expander(header, expanded=False):
            # Load full detail
            try:
                detail = api.admin_get_patient(pid)
            except Exception as e:
                st.error(f"Could not load: {e}"); continue

            # ── Patient info (two columns) ──
            d1, d2 = st.columns(2)
            with d1:
                with st.container(border=True):
                    st.markdown("**Personal Info**")
                    st.write(f"**Name:** {detail.get('full_name', '—')}")
                    st.write(f"**Phone:** {detail.get('phone') or '⚠️ Not set'}")
                    st.write(f"**DOB:** {detail.get('date_of_birth', '—')}  •  **Age:** {age_str}")
                    st.write(f"**Gender:** {(detail.get('gender') or '—').title()}")
                    st.write(f"**Blood Group:** {detail.get('blood_group') or '⚠️ Not set'}")
                    st.write(f"**ABHA/UHID:** {detail.get('abha_id') or '⚠️ Not set'}")
            with d2:
                with st.container(border=True):
                    st.markdown("**Emergency Contact**")
                    st.write(f"**Name:** {detail.get('emergency_contact_name') or '⚠️ Not set'}")
                    st.write(f"**Phone:** {detail.get('emergency_contact_phone') or '⚠️ Not set'}")
                    st.write(f"**Address:** {detail.get('address') or '⚠️ Not set'}")
                    st.write(f"**Risk Score:** {risk_dot} {risk:.1f}")

            # ── Family members ──
            rels = detail.get("relationships", [])
            if rels:
                st.markdown("**👨‍👩‍👧‍👦 Family Members / Beneficiaries**")
                for nri, r in enumerate(rels):
                    nb_pid = r.get("beneficiary_patient_id", "")
                    nb_name = r.get("beneficiary_name", "—")
                    nb_rel = (r.get("relationship_type") or "—").title()
                    rc1, rc2, rc3 = st.columns([3, 2, 1])
                    rc1.write(f"**{nb_name}**")
                    rc2.write(f"{nb_rel}")
                    if nb_pid:
                        with rc3.popover("👁️ View / Edit", use_container_width=True):
                            try:
                                nb_detail = api.admin_get_patient(nb_pid)
                                st.markdown(f"### {nb_detail.get('full_name', nb_name)}")
                                nbd1, nbd2 = st.columns(2)
                                with nbd1:
                                    st.write(f"**Email:** {nb_detail.get('email') or '—'}")
                                    st.write(f"**Phone:** {nb_detail.get('phone') or '—'}")
                                    st.write(f"**Gender:** {(nb_detail.get('gender') or '—').title()}")
                                    st.write(f"**DOB:** {nb_detail.get('date_of_birth') or '—'}")
                                    st.write(f"**Blood Group:** {nb_detail.get('blood_group') or '—'}")
                                with nbd2:
                                    st.write(f"**ABHA/UHID:** {nb_detail.get('abha_id') or '—'}")
                                    st.write(f"**Address:** {nb_detail.get('address') or '—'}")
                                    st.write(f"**Emergency:** {nb_detail.get('emergency_contact_name') or '—'}")
                                    st.write(f"**Emergency Ph:** {nb_detail.get('emergency_contact_phone') or '—'}")
                                    nb_risk = float(nb_detail.get('risk_score') or 0)
                                    nb_risk_dot = "🟢" if nb_risk < 3 else "🟡" if nb_risk < 7 else "🔴"
                                    st.write(f"**Risk:** {nb_risk_dot} {nb_risk:.1f}")
                                # Appointments
                                nb_appts = nb_detail.get("appointments", [])
                                if nb_appts:
                                    st.markdown(f"**Recent Appointments** ({len(nb_appts)})")
                                    for nba in nb_appts[:5]:
                                        nba_s = nba.get("status", "—")
                                        nba_icon = {"booked": "📅", "checked_in": "✅", "completed": "✔️",
                                                     "no_show": "⚠️", "cancelled": "❌"}.get(nba_s, "•")
                                        st.write(f"{nba_icon} {nba.get('session_date', '')} — "
                                                 f"Dr. {nba.get('doctor_name', '—')} ({nba.get('specialization', '')}) — "
                                                 f"{nba.get('slot_time', '')} — {nba_s}")
                                else:
                                    st.info("No appointments yet.")
                                # ── Edit beneficiary profile ──
                                st.divider()
                                st.markdown("**✏️ Edit Profile**")
                                nbe_name = st.text_input("Full Name", value=nb_detail.get("full_name") or nb_name, key=f"nbe_fn_{pid}_{nri}")
                                nbe_email = st.text_input("Email", value=nb_detail.get("email") or "", key=f"nbe_em_{pid}_{nri}")
                                nbe_phone = st.text_input("Phone", value=nb_detail.get("phone") or "", key=f"nbe_ph_{pid}_{nri}")
                                _nbe_g_opts = ["", "Male", "Female", "Other"]
                                _nbe_cur_g = nb_detail.get("gender") or ""
                                _nbe_gi = _nbe_g_opts.index(_nbe_cur_g) if _nbe_cur_g in _nbe_g_opts else 0
                                nbe_gender = st.selectbox("Gender", _nbe_g_opts, index=_nbe_gi, key=f"nbe_gn_{pid}_{nri}")
                                nbe_blood = st.selectbox("Blood Group",
                                                          ["", "A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"],
                                                          index=["", "A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"].index(nb_detail.get("blood_group") or ""),
                                                          key=f"nbe_bg_{pid}_{nri}")
                                nbe_abha = st.text_input("ABHA/UHID", value=nb_detail.get("abha_id") or "", key=f"nbe_abha_{pid}_{nri}")
                                nbe_addr = st.text_area("Address", value=nb_detail.get("address") or "", key=f"nbe_addr_{pid}_{nri}")
                                nbe_ec_name = st.text_input("Emergency Name", value=nb_detail.get("emergency_contact_name") or "", key=f"nbe_ecn_{pid}_{nri}")
                                nbe_ec_phone = st.text_input("Emergency Phone", value=nb_detail.get("emergency_contact_phone") or "", key=f"nbe_ecp_{pid}_{nri}")
                                if st.button("💾 Save Changes", key=f"nbe_save_{pid}_{nri}", type="primary", use_container_width=True):
                                    nb_payload = {}
                                    if nbe_name and nbe_name != (nb_detail.get("full_name") or nb_name): nb_payload["full_name"] = nbe_name
                                    if nbe_email and nbe_email != (nb_detail.get("email") or ""): nb_payload["email"] = nbe_email
                                    if nbe_phone and nbe_phone != (nb_detail.get("phone") or ""): nb_payload["phone"] = nbe_phone
                                    if nbe_gender and nbe_gender != (nb_detail.get("gender") or ""): nb_payload["gender"] = nbe_gender
                                    if nbe_blood and nbe_blood != (nb_detail.get("blood_group") or ""): nb_payload["blood_group"] = nbe_blood
                                    if nbe_abha and nbe_abha != (nb_detail.get("abha_id") or ""): nb_payload["abha_id"] = nbe_abha
                                    if nbe_addr and nbe_addr != (nb_detail.get("address") or ""): nb_payload["address"] = nbe_addr
                                    if nbe_ec_name and nbe_ec_name != (nb_detail.get("emergency_contact_name") or ""): nb_payload["emergency_contact_name"] = nbe_ec_name
                                    if nbe_ec_phone and nbe_ec_phone != (nb_detail.get("emergency_contact_phone") or ""): nb_payload["emergency_contact_phone"] = nbe_ec_phone
                                    if nb_payload:
                                        try:
                                            api.admin_update_patient(nb_pid, nb_payload)
                                            st.session_state["nurse_pat_msg"] = f"Profile updated for {nbe_name or nb_name}"
                                            st.rerun()
                                        except Exception as ex:
                                            st.error(f"{ex}")
                                    else:
                                        st.info("No changes to save.")
                            except Exception as e:
                                st.error(f"Could not load details: {e}")

            # ── Appointment history (last 10) ──
            appts = detail.get("appointments", [])
            if appts:
                st.markdown(f"**📋 Recent Appointments** ({len(appts)})")
                for a in appts[:10]:
                    a_status = a.get("status", "—")
                    s_cfg = {
                        "booked": "📅", "checked_in": "✅", "in_progress": "🔄",
                        "completed": "✔️", "no_show": "⚠️", "cancelled": "❌",
                    }
                    a_icon = s_cfg.get(a_status, "•")
                    with st.container(border=True):
                        ac1, ac2, ac3 = st.columns([2, 3, 2])
                        ac1.write(f"{a_icon} {a_status.replace('_', ' ').title()}")
                        ac2.write(f"📅 {a.get('session_date', '—')}  •  🩺 {a.get('doctor_name', '—')}")
                        ac3.write(f"{a.get('specialization', '')}")

            # ── Nurse actions ──
            st.divider()
            st.markdown("**⚙️ Actions**")
            na1, na2 = st.columns(2)

            # Book appointment (with beneficiary picker)
            with na1.popover("📅 Book Appointment", use_container_width=True):
                st.markdown("**Book Appointment**")
                # Who is this for?
                nbk_opts = [f"{name} (Self)"]
                nbk_ids = {0: pid}
                for ri, rel in enumerate(rels):
                    bname = rel.get("beneficiary_name", "?")
                    rtype = (rel.get("relationship_type") or "other").title()
                    nbk_opts.append(f"{bname} ({rtype})")
                    nbk_ids[ri + 1] = rel.get("beneficiary_patient_id", pid)
                nbk_for = st.radio("Booking for", nbk_opts, key=f"nbk_for_{pid}")
                nbk_sel = nbk_opts.index(nbk_for) if nbk_for in nbk_opts else 0
                nbk_pid = nbk_ids.get(nbk_sel, pid)
                nbk_name = nbk_for.split(" (")[0]

                st.divider()
                try:
                    nbk_docs = api.list_doctors()
                except Exception:
                    nbk_docs = []
                nbk_depts = sorted(set(d.get("specialization", "") for d in nbk_docs if d.get("specialization")))
                nbk_dept = st.selectbox("Department", ["All"] + nbk_depts, key=f"nbk_dept_{pid}")
                if nbk_dept != "All":
                    nbk_docs = [d for d in nbk_docs if d.get("specialization") == nbk_dept]
                if not nbk_docs:
                    st.warning("No doctors available.")
                else:
                    nbk_doc_labels = [f"{d['full_name']} ({d['specialization']})" for d in nbk_docs]
                    nbk_doc_idx = st.selectbox("Doctor", range(len(nbk_doc_labels)),
                                                format_func=lambda i: nbk_doc_labels[i], key=f"nbk_doc_{pid}")
                    nbk_doc = nbk_docs[nbk_doc_idx]

                    # ── Date picker ──
                    from datetime import date as _nbk_d
                    _nbk_today = _nbk_d.today()
                    nbk_date = st.date_input("📅 Date", value=_nbk_today, key=f"nbk_date_{pid}")
                    nbk_from, nbk_to = nbk_date, nbk_date

                    # Load ALL sessions for the date range
                    try:
                        nbk_sessions = api.get_doctor_sessions(
                            nbk_doc["doctor_id"],
                            from_date=str(nbk_from),
                            to_date=str(nbk_to),
                            include_all=True,
                        )
                        nbk_bookable = [s for s in nbk_sessions if s.get("status") in ("active", "inactive")]
                    except Exception:
                        nbk_bookable = []
                    if not nbk_bookable:
                        st.info(f"No sessions found for {nbk_doc['full_name']} in the selected date range. "
                                f"The doctor may not have sessions scheduled, or all sessions are completed/cancelled.")
                    else:
                        def _nbk_sess_label(s):
                            tag = ""
                            if s.get("status") == "inactive":
                                tag = " ⚪ INACTIVE"
                            cap = s.get('available_capacity', '?')
                            return (f"{s['session_date']} • "
                                    f"{str(s.get('start_time', ''))[:5]}–{str(s.get('end_time', ''))[:5]} • "
                                    f"{cap} slots avail{tag}")

                        nbk_sess_labels = [_nbk_sess_label(s) for s in nbk_bookable]
                        nbk_sess_idx = st.selectbox("Session", range(len(nbk_sess_labels)),
                                                     format_func=lambda i: nbk_sess_labels[i], key=f"nbk_sess_{pid}")
                        nbk_sess = nbk_bookable[nbk_sess_idx]

                        if nbk_sess.get("status") == "inactive":
                            st.warning("⚪ This session is **inactive**. Activate it first, or ask the doctor to activate from their dashboard.")
                            if st.button("🟢 Activate & Continue", key=f"nbk_activate_{pid}"):
                                try:
                                    api.activate_session({"session_id": nbk_sess["session_id"]})
                                    st.success("Session activated!")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Failed: {e}")
                        else:
                            nbk_total = nbk_sess.get("total_slots", 1)
                            nbk_dur = nbk_sess.get("slot_duration_minutes", 15)
                            nbk_start = str(nbk_sess.get("start_time", "09:00"))
                            from datetime import datetime as _nbk_dt
                            _nbk_now_min = _nbk_dt.now().hour * 60 + _nbk_dt.now().minute
                            _nbk_is_today = str(nbk_date) == str(_nbk_d.today())
                            nbk_slot_opts = []  # list of (slot_number, label)
                            for si in range(1, nbk_total + 1):
                                try:
                                    hh, mm = int(nbk_start[:2]), int(nbk_start[3:5])
                                    t_min = hh * 60 + mm + (si - 1) * nbk_dur
                                    if _nbk_is_today and t_min + nbk_dur <= _nbk_now_min:
                                        continue
                                    t_str = f"{t_min // 60:02d}:{t_min % 60:02d}"
                                except Exception:
                                    t_str = f"Slot {si}"
                                nbk_slot_opts.append((si, f"Slot {si} — {t_str}"))
                            if not nbk_slot_opts:
                                st.warning("All time slots for this session have already passed.")
                            else:
                                nbk_slot_idx = st.selectbox("Time Slot", range(len(nbk_slot_opts)),
                                                             format_func=lambda i: nbk_slot_opts[i][1], key=f"nbk_slot_{pid}")
                                nbk_slot_num = nbk_slot_opts[nbk_slot_idx][0]
                                st.caption(f"**Patient:** {nbk_name}  •  **Doctor:** {nbk_doc['full_name']}  •  **Slot:** {nbk_slot_opts[nbk_slot_idx][1]}")
                                if st.button("✅ Confirm Booking", key=f"nbk_confirm_{pid}", type="primary", use_container_width=True):
                                    try:
                                        api.staff_book({
                                            "session_id": nbk_sess["session_id"],
                                            "patient_id": nbk_pid,
                                            "slot_number": nbk_slot_num,
                                        })
                                        st.session_state["nurse_pat_msg"] = f"Booked for {nbk_name} with {nbk_doc['full_name']}"
                                        st.rerun()
                                    except Exception as ex:
                                        st.error(f"Booking failed: {ex}")

            # Edit profile
            with na2.popover("✏️ Update Info", use_container_width=True):
                st.markdown("**Edit Patient Profile**")
                np_name = st.text_input("Full Name", value=detail.get("full_name") or name or "", key=f"np_fn_{pid}")
                np_email = st.text_input("Email", value=detail.get("email") or "", key=f"np_em_{pid}")
                np_phone = st.text_input("Phone", value=detail.get("phone") or "", key=f"np_ph_{pid}")
                _np_gender_opts = ["", "Male", "Female", "Other"]
                _np_cur_gender = detail.get("gender") or ""
                _np_gi = _np_gender_opts.index(_np_cur_gender) if _np_cur_gender in _np_gender_opts else 0
                np_gender = st.selectbox("Gender", _np_gender_opts, index=_np_gi, key=f"np_gn_{pid}")
                np_blood = st.selectbox("Blood Group",
                                         ["", "A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"],
                                         index=["", "A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"].index(detail.get("blood_group") or ""),
                                         key=f"np_bg_{pid}")
                np_abha = st.text_input("ABHA/UHID", value=detail.get("abha_id") or "", key=f"np_abha_{pid}")
                np_addr = st.text_area("Address", value=detail.get("address") or "", key=f"np_addr_{pid}")
                st.divider()
                st.markdown("**Emergency Contact**")
                np_ec_name = st.text_input("Emergency Name", value=detail.get("emergency_contact_name") or "", key=f"np_ecn_{pid}")
                np_ec_phone = st.text_input("Emergency Phone", value=detail.get("emergency_contact_phone") or "", key=f"np_ecp_{pid}")
                if st.button("💾 Save", key=f"np_save_{pid}", type="primary", use_container_width=True):
                    payload = {}
                    if np_name and np_name != (detail.get("full_name") or name or ""): payload["full_name"] = np_name
                    if np_email and np_email != (detail.get("email") or ""): payload["email"] = np_email
                    if np_phone and np_phone != (detail.get("phone") or ""): payload["phone"] = np_phone
                    if np_gender and np_gender != (detail.get("gender") or ""): payload["gender"] = np_gender
                    if np_blood and np_blood != (detail.get("blood_group") or ""): payload["blood_group"] = np_blood
                    if np_abha and np_abha != (detail.get("abha_id") or ""): payload["abha_id"] = np_abha
                    if np_ec_name and np_ec_name != (detail.get("emergency_contact_name") or ""): payload["emergency_contact_name"] = np_ec_name
                    if np_ec_phone and np_ec_phone != (detail.get("emergency_contact_phone") or ""): payload["emergency_contact_phone"] = np_ec_phone
                    if np_addr and np_addr != (detail.get("address") or ""): payload["address"] = np_addr
                    if payload:
                        try:
                            api.admin_update_patient(pid, payload)
                            st.session_state["nurse_pat_msg"] = f"Updated {np_name or name}"
                            st.rerun()
                        except Exception as e:
                            st.error(f"{e}")
                    else:
                        st.info("No changes.")


# ════════════════════════════════════════════════════════════
# ADMIN: CANCEL SESSION
# ════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════
# ADMIN DASHBOARD — FULL SYSTEM CONTROL
# ════════════════════════════════════════════════════════════

def page_admin_dashboard():
    """Admin overview — today's stats at a glance."""
    tc1, tc2 = st.columns([6, 1])
    tc1.title("🏠 Admin Dashboard")
    if tc2.button("🔄 Refresh", key="refresh_admin_dash", use_container_width=True):
        st.rerun()
    try:
        stats = api.admin_stats()
    except Exception as e:
        st.error(f"Failed to load stats: {e}")
        return

    # ── Top KPI row ──
    k1, k2, k3, k4 = st.columns(4)
    sess = stats.get("sessions", {})
    appt = stats.get("appointments", {})
    users = stats.get("users", {})

    k1.metric("Sessions Today", sess.get("total", 0),
              f"{sess.get('active', 0)} active")
    k2.metric("Appointments", appt.get("total", 0),
              f"{appt.get('completed', 0)} done")
    k3.metric("Active Doctors", stats.get("active_doctors_today", 0))
    k4.metric("High-Risk Patients", stats.get("high_risk_patients", 0))

    st.divider()

    # ── Sessions breakdown ──
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### Sessions")
        for key in ["active", "inactive", "completed", "cancelled"]:
            val = sess.get(key, 0)
            colors = {"active": "🟢", "inactive": "🟡", "completed": "✅", "cancelled": "❌"}
            st.write(f"{colors.get(key, '•')} **{key.title()}**: {val}")

    with c2:
        st.markdown("### Appointments")
        for key in ["booked", "checked_in", "in_progress", "completed", "no_show", "cancelled", "emergencies"]:
            val = appt.get(key, 0)
            icons = {"booked": "📅", "checked_in": "✅", "in_progress": "🔄",
                     "completed": "✔️", "no_show": "⚠️", "cancelled": "❌", "emergencies": "🚨"}
            st.write(f"{icons.get(key, '•')} **{key.replace('_', ' ').title()}**: {val}")

    st.divider()

    # ── User summary ──
    st.markdown("### System Users")
    u1, u2, u3, u4, u5 = st.columns(5)
    u1.metric("Total", users.get("total", 0))
    u2.metric("Patients", users.get("patients", 0))
    u3.metric("Doctors", users.get("doctors", 0))
    u4.metric("Nurses", users.get("nurses", 0))
    u5.metric("Admins", users.get("admins", 0))
    if users.get("deactivated", 0) > 0:
        st.caption(f"⚠️ {users['deactivated']} deactivated users")


def page_admin_users():
    """User management — create, view, activate/deactivate staff."""
    tc1, tc2 = st.columns([6, 1])
    tc1.title("👥 User Management")
    if tc2.button("🔄 Refresh", key="refresh_admin_users", use_container_width=True):
        st.rerun()

    # ── Persistent message ──
    if st.session_state.get("admin_msg"):
        st.success(st.session_state.pop("admin_msg"))

    tab_list, tab_create = st.tabs(["📋 All Users", "➕ Create Staff"])

    # ── TAB 1: List users ──
    with tab_list:
        fc1, fc2, fc3 = st.columns([2, 2, 1])
        role_filter = fc1.selectbox("Filter by role",
                                     ["all", "doctor", "nurse", "admin", "patient"],
                                     key="admin_user_role")
        # Department filter (only meaningful for doctors)
        try:
            depts = ["all"] + api.admin_list_departments()
        except Exception:
            depts = ["all"]
        dept_filter = fc2.selectbox("Department", depts, key="admin_user_dept",
                                     disabled=(role_filter not in ("all", "doctor")))
        show_inactive = fc3.checkbox("Show inactive", key="admin_show_inactive")

        try:
            users = api.admin_list_users(
                role="" if role_filter == "all" else role_filter,
                include_inactive=show_inactive,
            )
        except Exception as e:
            st.error(f"Failed: {e}")
            return

        # Client-side department filter: match doctor users against doctor list
        if dept_filter != "all" and role_filter in ("all", "doctor"):
            try:
                dept_docs = api.admin_list_doctors(specialization=dept_filter)
                dept_user_ids = {d["user_id"] for d in dept_docs}
                users = [u for u in users if u["role"] != "doctor" or u["id"] in dept_user_ids]
                if role_filter == "doctor":
                    users = [u for u in users if u["id"] in dept_user_ids]
            except Exception:
                pass

        if not users:
            st.info("No users found.")
            return

        for u in users:
            uid = str(u["id"])
            active = str(u.get("is_active", "True")).lower() == "true"
            role_icon = {"doctor": "🩺", "nurse": "💉", "admin": "🔧", "patient": "👤"}.get(u["role"], "•")
            status_dot = "🟢" if active else "🔴"

            with st.container(border=True):
                uc1, uc2, uc3 = st.columns([4, 1, 1])
                uc1.markdown(
                    f"{status_dot} {role_icon} **{u['full_name']}**  "
                    f"({u['role']})  •  {u.get('email', '—')}  •  📞 {u.get('phone') or '—'}"
                )
                uc2.caption(f"Since {str(u.get('created_at', ''))[:10]}")

                # Toggle button
                btn_label = "Deactivate" if active else "Activate"
                if u["role"] != "admin" or uid != str(st.session_state.user.get("user_id")):
                    if uc3.button(btn_label, key=f"toggle_{uid}", use_container_width=True):
                        try:
                            r = api.admin_toggle_user(uid)
                            st.session_state["admin_msg"] = r["message"]
                            st.rerun()
                        except Exception as e:
                            st.error(f"{e}")

    # ── TAB 2: Create staff ──
    with tab_create:
        with st.form("create_staff_form"):
            st.markdown("**New Staff Member**")
            cs1, cs2 = st.columns(2)
            cs_name = cs1.text_input("Full Name *", placeholder="Dr. Priya Sharma")
            cs_email = cs2.text_input("Email *", placeholder="priya@hospital.com")

            cs3, cs4, cs5 = st.columns(3)
            cs_phone = cs3.text_input("Phone", placeholder="9876543210")
            cs_password = cs4.text_input("Password *", type="password")
            cs_role = cs5.selectbox("Role *", ["doctor", "nurse", "admin"])

            # Doctor-specific fields
            if cs_role == "doctor":
                st.markdown("**Doctor Details**")
                dc1, dc2 = st.columns(2)
                dc_spec = dc1.text_input("Specialization *", placeholder="Cardiology")
                dc_qual = dc2.text_input("Qualification *", placeholder="MBBS, MD")
                dc3, dc4, dc5 = st.columns(3)
                dc_license = dc3.text_input("License Number *", placeholder="MCI-12345")
                dc_fee = dc4.number_input("Consultation Fee (₹)", 0, 10000, 500)
                dc_max = dc5.number_input("Max Patients/Slot", 1, 10, 2)

            if st.form_submit_button("✅ Create", type="primary", use_container_width=True):
                if not cs_name or not cs_email or not cs_password:
                    st.error("Name, email, and password are required.")
                else:
                    payload = {
                        "full_name": cs_name.strip(),
                        "email": cs_email.strip(),
                        "phone": cs_phone.strip(),
                        "password": cs_password,
                        "role": cs_role,
                    }
                    if cs_role == "doctor":
                        payload.update({
                            "specialization": dc_spec.strip(),
                            "qualification": dc_qual.strip(),
                            "license_number": dc_license.strip(),
                            "consultation_fee": dc_fee,
                            "max_patients_per_slot": dc_max,
                        })
                    try:
                        r = api.admin_create_user(payload)
                        st.session_state["admin_msg"] = r["message"]
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed: {e}")


def page_admin_doctors():
    """Doctor management — view all, toggle availability, edit settings."""
    tc1, tc2 = st.columns([6, 1])
    tc1.title("🩺 Doctor Management")
    if tc2.button("🔄 Refresh", key="refresh_admin_docs", use_container_width=True):
        st.rerun()

    if st.session_state.get("admin_msg"):
        st.success(st.session_state.pop("admin_msg"))

    # Department filter
    try:
        depts = ["All"] + api.admin_list_departments()
    except Exception:
        depts = ["All"]
    dept_sel = st.selectbox("Filter by Department", depts, key="admin_doc_dept")

    try:
        doctors = api.admin_list_doctors(
            specialization="" if dept_sel == "All" else dept_sel
        )
    except Exception as e:
        st.error(f"Failed to load doctors: {e}")
        return

    if not doctors:
        st.info("No doctors registered.")
        return

    # Group by department
    by_dept = {}
    for doc in doctors:
        dept = doc.get("specialization") or "Other"
        if dept not in by_dept:
            by_dept[dept] = []
        by_dept[dept].append(doc)

    for dept in sorted(by_dept.keys()):
        st.subheader(f"🏥 {dept}")
        for doc in by_dept[dept]:
            did = str(doc["doctor_id"])
            avail = str(doc.get("is_available", "True")).lower() == "true"
            user_active = str(doc.get("user_active", "True")).lower() == "true"
            avail_badge = "🟢 Available" if avail else "🔴 Unavailable"
            user_badge = "" if user_active else " *(deactivated)*"

            try:
                fee_val = int(float(doc.get("consultation_fee", 500)))
            except (ValueError, TypeError):
                fee_val = 500
            try:
                max_val = int(doc.get("max_patients_per_slot", 2))
            except (ValueError, TypeError):
                max_val = 2

            with st.expander(f"{'🟢' if avail else '🔴'} {doc['full_name']} | {avail_badge}{user_badge}", expanded=False):
                i1, i2 = st.columns(2)
                i1.write(f"**Email**: {doc.get('email') or '—'}")
                i1.write(f"**Phone**: {doc.get('phone') or '—'}")
                i1.write(f"**Qualification**: {doc.get('qualification') or '—'}")
                i2.write(f"**License**: {doc.get('license_number') or '—'}")
                i2.write(f"**Fee**: ₹{fee_val}")
                i2.write(f"**Max/Slot**: {max_val}")

                st.divider()
                ac1, ac2 = st.columns(2)

                new_avail = not avail
                avail_label = "Set Available" if new_avail else "Set Unavailable"
                if ac1.button(avail_label, key=f"avail_{did}", use_container_width=True):
                    try:
                        api.admin_update_doctor(did, {"is_available": new_avail})
                        st.session_state["admin_msg"] = f"{'Enabled' if new_avail else 'Disabled'} {doc['full_name']}"
                        st.rerun()
                    except Exception as e:
                        st.error(f"{e}")

                with ac2.popover("✏️ Edit Settings"):
                    # doctor_name = st.text_input("Doctor Name", value=doc.get("full_name") or "", key=f"ed_name_{did}")
                    ed_fee = st.number_input("Fee (₹)", 0, 10000, fee_val, key=f"ed_fee_{did}")
                    ed_max = st.number_input("Max/Slot", 1, 10, max_val, key=f"ed_max_{did}")
                    ed_spec = st.text_input("Specialization", doc.get("specialization") or "", key=f"ed_spec_{did}")
                    if st.button("Save", key=f"ed_save_{did}", type="primary", use_container_width=True):
                        updates = {}


                        # if doctor_name!= (doc.get("full_name") or ""):
                        #     updates["full_name"] = doctor_name



                        if ed_fee != fee_val:
                            updates["consultation_fee"] = ed_fee
                        if ed_max != max_val:
                            updates["max_patients_per_slot"] = ed_max
                        if ed_spec != (doc.get("specialization") or ""):
                            updates["specialization"] = ed_spec
                        if updates:
                            try:
                                api.admin_update_doctor(did, updates)
                                st.session_state["admin_msg"] = f"Updated {doc['full_name']}"
                                st.rerun()
                            except Exception as e:
                                st.error(f"{e}")
                        else:
                            st.info("No changes")


def page_admin_config():
    """System configuration — scheduling_config key-value store."""
    tc1, tc2 = st.columns([6, 1])
    tc1.title("⚙️ System Configuration")
    if tc2.button("🔄 Refresh", key="refresh_admin_config", use_container_width=True):
        st.rerun()

    if st.session_state.get("admin_msg"):
        st.success(st.session_state.pop("admin_msg"))

    try:
        configs = api.admin_get_config()
    except Exception as e:
        st.error(f"Failed to load config: {e}")
        return

    if not configs:
        st.info("No configuration entries found.")
        return

    for cfg in configs:
        key = cfg["config_key"]
        val = cfg["config_value"]
        desc = cfg.get("description") or ""
        updated = str(cfg.get("updated_at", ""))[:19]

        with st.container(border=True):
            cc1, cc2 = st.columns([3, 1])
            cc1.markdown(f"**{key}**")
            if desc:
                cc1.caption(desc)
            cc1.code(str(val), language=None)
            cc1.caption(f"Last updated: {updated}")

            with cc2.popover("✏️ Edit"):
                # Determine input type based on current value
                if isinstance(val, bool):
                    new_val = st.checkbox("Value", value=val, key=f"cfg_{key}")
                elif isinstance(val, (int, float)):
                    new_val = st.number_input("Value", value=float(val), key=f"cfg_{key}")
                else:
                    new_val = st.text_input("Value", value=str(val), key=f"cfg_{key}")

                if st.button("Save", key=f"cfg_save_{key}", type="primary", use_container_width=True):
                    try:
                        api.admin_update_config(key, {"value": new_val})
                        st.session_state["admin_msg"] = f"Config '{key}' updated to {new_val}"
                        st.rerun()
                    except Exception as e:
                        st.error(f"{e}")


def page_admin_patients():
    """Patient management — search, view details, manage appointments, edit profiles, reset risks."""
    from datetime import date as _d, datetime as _dt

    tc1, tc2 = st.columns([6, 1])
    tc1.title("🏥 Patient Management")
    if tc2.button("🔄 Refresh", key="refresh_admin_pat", use_container_width=True):
        st.rerun()

    if st.session_state.get("admin_msg"):
        st.success(st.session_state.pop("admin_msg"))

    # Load doctors for filters
    try:
        all_docs = api.admin_list_doctors()
    except Exception:
        all_docs = []
    departments = sorted(set(d.get("specialization", "") for d in all_docs if d.get("specialization")))

    # ── Filters ──
    fc1, fc2, fc3, fc4, fc5 = st.columns([3, 2, 2, 1, 1])
    search = fc1.text_input("🔍 Search", key="admin_pat_search", placeholder="Name, phone, or ABHA...")
    filter_dept = fc2.selectbox("Department", ["All"] + departments, key="admin_pat_dept")
    if filter_dept != "All":
        dept_docs = [d for d in all_docs if d.get("specialization") == filter_dept]
    else:
        dept_docs = all_docs
    doc_names = ["All"] + [d["full_name"] for d in dept_docs]
    filter_doc = fc3.selectbox("Doctor", doc_names, key="admin_pat_doc")
    high_risk = fc4.checkbox("High risk", key="admin_pat_hr")
    show_inactive = fc5.checkbox("Deactivated", key="admin_pat_inactive")

    sel_doc_id = ""
    if filter_doc != "All":
        match = [d for d in dept_docs if d["full_name"] == filter_doc]
        if match:
            sel_doc_id = str(match[0]["doctor_id"])

    try:
        patients = api.admin_list_patients(
            search=search if search and len(search) >= 2 else "",
            high_risk_only=high_risk,
            include_inactive=show_inactive,
            specialization="" if filter_dept == "All" else filter_dept,
            doctor_id=sel_doc_id,
        )
    except Exception as e:
        st.error(f"Failed: {e}"); return

    if not patients:
        st.info("No patients found."); return

    # ── Summary metrics ──
    total = len(patients)
    hr_count = sum(1 for p in patients if float(p.get("risk_score") or 0) >= 7)
    total_visits = sum(int(p.get("total_appointments") or 0) for p in patients)
    total_noshow = sum(int(p.get("no_shows") or 0) for p in patients)
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Patients", total)
    mc2.metric("High Risk", hr_count)
    mc3.metric("Total Visits", total_visits)
    mc4.metric("Total No-Shows", total_noshow)
    st.divider()

    # ── Patient list — click to expand full details ──
    for p in patients:
        pid = str(p["patient_id"])
        try:
            risk = float(p.get("risk_score") or 0)
        except (ValueError, TypeError):
            risk = 0.0
        risk_dot = "🟢" if risk < 3 else "🟡" if risk < 7 else "🔴"
        try:
            total_appt = int(p.get("total_appointments") or 0)
        except (ValueError, TypeError):
            total_appt = 0
        try:
            no_shows = int(p.get("no_shows") or 0)
        except (ValueError, TypeError):
            no_shows = 0
        ns_rate = f"{(no_shows / total_appt * 100):.0f}%" if total_appt > 0 else "—"

        age_str = ""
        if p.get("date_of_birth") and p["date_of_birth"] != "None":
            try:
                dob = _d.fromisoformat(str(p["date_of_birth"])[:10])
                age_str = f"{(_d.today() - dob).days // 365}y"
            except Exception:
                pass
        gender_str = (p.get("gender") or "—")[:1].upper() if p.get("gender") and p["gender"] != "None" else "—"
        name = p.get("full_name", "—")
        p_active = p.get("is_active") not in ("False", "false", False)
        inactive_tag = "  •  🚫 DEACTIVATED" if not p_active else ""

        header = (
            f"{risk_dot} **{name}**{inactive_tag}  •  {age_str}/{gender_str}  "
            f"•  📞 {p.get('phone') or '—'}  •  🩸 {p.get('blood_group') or '—'}  "
            f"•  Visits: {total_appt}  •  No-shows: {no_shows} ({ns_rate})"
        )

        with st.expander(header, expanded=False):
            # ── Load full patient detail on expand ──
            try:
                detail = api.admin_get_patient(pid)
            except Exception as e:
                st.error(f"Could not load details: {e}"); continue

            # ── Profile info (two columns) ──
            d1, d2 = st.columns(2)
            with d1:
                with st.container(border=True):
                    st.markdown("**Personal Info**")
                    st.write(f"**Name:** {detail.get('full_name', '—')}")
                    st.write(f"**Email:** {detail.get('email', '—')}")
                    st.write(f"**Phone:** {detail.get('phone') or '⚠️ Not set'}")
                    st.write(f"**DOB:** {detail.get('date_of_birth', '—')}  •  **Age:** {age_str}")
                    st.write(f"**Gender:** {(detail.get('gender') or '—').title()}")
                    st.write(f"**Blood Group:** {detail.get('blood_group') or '⚠️ Not set'}")
                    st.write(f"**ABHA/UHID:** {detail.get('abha_id') or '⚠️ Not set'}")

            with d2:
                with st.container(border=True):
                    st.markdown("**Emergency & Risk**")
                    st.write(f"**Emergency Contact:** {detail.get('emergency_contact_name') or '⚠️ Not set'}")
                    st.write(f"**Emergency Phone:** {detail.get('emergency_contact_phone') or '⚠️ Not set'}")
                    st.write(f"**Address:** {detail.get('address') or '⚠️ Not set'}")
                    st.write(f"**Risk Score:** {risk_dot} {risk:.1f}")
                    st.write(f"**Account Active:** {'✅ Yes' if detail.get('is_active') == 'True' else '❌ No'}")
                    st.write(f"**Registered:** {str(detail.get('created_at', ''))[:10]}")

            # ── Family members / Relationships ──
            rels = detail.get("relationships", [])
            if rels:
                st.markdown("**👨‍👩‍👧‍👦 Family Members / Beneficiaries**")
                for ri, r in enumerate(rels):
                    b_pid = r.get("beneficiary_patient_id", "")
                    b_name = r.get("beneficiary_name", "—")
                    b_rel = (r.get("relationship_type") or "—").title()
                    b_approved = r.get("is_approved") in (True, "True", "true")
                    rc1, rc2, rc3, rc4 = st.columns([3, 2, 1, 1])
                    rc1.write(f"**{b_name}**")
                    rc2.write(f"Relation: {b_rel}")
                    rc3.write("✅ Linked" if b_approved else "⏳ Pending")
                    # View & Edit beneficiary details
                    if b_pid:
                        with rc4.popover("👁️ View", use_container_width=True):
                            try:
                                b_detail = api.admin_get_patient(b_pid)
                                st.markdown(f"### {b_detail.get('full_name', b_name)}")
                                bd1, bd2 = st.columns(2)
                                with bd1:
                                    st.write(f"**Email:** {b_detail.get('email') or '—'}")
                                    st.write(f"**Phone:** {b_detail.get('phone') or '—'}")
                                    st.write(f"**Gender:** {(b_detail.get('gender') or '—').title()}")
                                    st.write(f"**DOB:** {b_detail.get('date_of_birth') or '—'}")
                                    st.write(f"**Blood Group:** {b_detail.get('blood_group') or '—'}")
                                with bd2:
                                    st.write(f"**ABHA/UHID:** {b_detail.get('abha_id') or '—'}")
                                    st.write(f"**Address:** {b_detail.get('address') or '—'}")
                                    st.write(f"**Emergency:** {b_detail.get('emergency_contact_name') or '—'}")
                                    st.write(f"**Emergency Ph:** {b_detail.get('emergency_contact_phone') or '—'}")
                                    b_risk = float(b_detail.get('risk_score') or 0)
                                    b_risk_dot = "🟢" if b_risk < 3 else "🟡" if b_risk < 7 else "🔴"
                                    st.write(f"**Risk:** {b_risk_dot} {b_risk:.1f}")
                                # Beneficiary appointments
                                b_appts = b_detail.get("appointments", [])
                                if b_appts:
                                    st.markdown(f"**Recent Appointments** ({len(b_appts)})")
                                    for ba in b_appts[:5]:
                                        ba_s = ba.get("status", "—")
                                        ba_icon = {"booked": "📅", "checked_in": "✅", "completed": "✔️",
                                                    "no_show": "⚠️", "cancelled": "❌"}.get(ba_s, "•")
                                        st.write(f"{ba_icon} {ba.get('session_date', '')} — "
                                                 f"Dr. {ba.get('doctor_name', '—')} ({ba.get('specialization', '')}) — "
                                                 f"{ba.get('slot_time', '')} — {ba_s}")
                                else:
                                    st.info("No appointments yet.")

                                # ── Edit beneficiary profile ──
                                st.divider()
                                st.markdown("**✏️ Edit Profile**")
                                be_name = st.text_input("Full Name", value=b_detail.get("full_name") or b_name, key=f"be_fn_{pid}_{ri}")
                                be_email = st.text_input("Email", value=b_detail.get("email") or "", key=f"be_em_{pid}_{ri}")
                                be_phone = st.text_input("Phone", value=b_detail.get("phone") or "", key=f"be_ph_{pid}_{ri}")
                                _be_g_opts = ["", "Male", "Female", "Other"]
                                _be_cur_g = b_detail.get("gender") or ""
                                _be_gi = _be_g_opts.index(_be_cur_g) if _be_cur_g in _be_g_opts else 0
                                be_gender = st.selectbox("Gender", _be_g_opts, index=_be_gi, key=f"be_gn_{pid}_{ri}")
                                be_blood = st.selectbox("Blood Group",
                                                         ["", "A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"],
                                                         index=["", "A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"].index(b_detail.get("blood_group") or ""),
                                                         key=f"be_bg_{pid}_{ri}")
                                be_abha = st.text_input("ABHA/UHID", value=b_detail.get("abha_id") or "", key=f"be_abha_{pid}_{ri}")
                                be_addr = st.text_area("Address", value=b_detail.get("address") or "", key=f"be_addr_{pid}_{ri}")
                                be_ec_name = st.text_input("Emergency Name", value=b_detail.get("emergency_contact_name") or "", key=f"be_ecn_{pid}_{ri}")
                                be_ec_phone = st.text_input("Emergency Phone", value=b_detail.get("emergency_contact_phone") or "", key=f"be_ecp_{pid}_{ri}")
                                if st.button("💾 Save Changes", key=f"be_save_{pid}_{ri}", type="primary", use_container_width=True):
                                    b_payload = {}
                                    if be_name and be_name != (b_detail.get("full_name") or b_name): b_payload["full_name"] = be_name
                                    if be_email and be_email != (b_detail.get("email") or ""): b_payload["email"] = be_email
                                    if be_phone and be_phone != (b_detail.get("phone") or ""): b_payload["phone"] = be_phone
                                    if be_gender and be_gender != (b_detail.get("gender") or ""): b_payload["gender"] = be_gender
                                    if be_blood and be_blood != (b_detail.get("blood_group") or ""): b_payload["blood_group"] = be_blood
                                    if be_abha and be_abha != (b_detail.get("abha_id") or ""): b_payload["abha_id"] = be_abha
                                    if be_addr and be_addr != (b_detail.get("address") or ""): b_payload["address"] = be_addr
                                    if be_ec_name and be_ec_name != (b_detail.get("emergency_contact_name") or ""): b_payload["emergency_contact_name"] = be_ec_name
                                    if be_ec_phone and be_ec_phone != (b_detail.get("emergency_contact_phone") or ""): b_payload["emergency_contact_phone"] = be_ec_phone
                                    if b_payload:
                                        try:
                                            api.admin_update_patient(b_pid, b_payload)
                                            st.session_state["admin_msg"] = f"Profile updated for {be_name or b_name}"
                                            st.rerun()
                                        except Exception as ex:
                                            st.error(f"{ex}")
                                    else:
                                        st.info("No changes to save.")
                            except Exception as e:
                                st.error(f"Could not load details: {e}")

            # ── Appointment history ──
            appts = detail.get("appointments", [])
            st.markdown(f"**📋 Appointment History** ({len(appts)} recent)")
            if appts:
                for a in appts:
                    a_status = a.get("status", "—")
                    a_id = a.get("appointment_id", "")
                    s_cfg = {
                        "booked": ("📅", "#3b82f6"),
                        "checked_in": ("✅", "#f59e0b"),
                        "in_progress": ("🔄", "#8b5cf6"),
                        "completed": ("✔️", "#22c55e"),
                        "no_show": ("⚠️", "#ef4444"),
                        "cancelled": ("❌", "#9ca3af"),
                    }
                    a_icon, a_color = s_cfg.get(a_status, ("•", "#666"))
                    slot_t = a.get("slot_time") or str(a.get("start_time", ""))[:5]
                    a_date = a.get("session_date", "—")
                    doc_name = a.get("doctor_name", "—")
                    spec = a.get("specialization", "")

                    with st.container(border=True):
                        ac1, ac2, ac3, ac4 = st.columns([2, 2, 2, 2])
                        ac1.write(f"{a_icon} **{a_status.replace('_', ' ').title()}**")
                        ac2.write(f"📅 {a_date}  •  🕐 {slot_t}")
                        ac3.write(f"🩺 {doc_name} ({spec})")
                        # Action buttons based on status
                        if a_status == "booked":
                            bc1, bc2 = ac4.columns(2)
                            if bc1.button("✖ Cancel", key=f"adm_cx_{a_id}", use_container_width=True):
                                try:
                                    api.staff_cancel_appointment({"appointment_id": a_id, "reason": "Cancelled by admin"})
                                    st.session_state["admin_msg"] = f"Cancelled appointment for {name}"
                                    st.rerun()
                                except Exception as ex:
                                    st.error(f"{ex}")
                        elif a_status == "no_show":
                            if ac4.button("↩ Undo", key=f"adm_uns_{a_id}", use_container_width=True):
                                try:
                                    api.undo_noshow({"appointment_id": a_id})
                                    st.session_state["admin_msg"] = f"No-show undone for {name}"
                                    st.rerun()
                                except Exception as ex:
                                    st.error(f"{ex}")
                        elif a_status == "cancelled":
                            if ac4.button("↩ Restore", key=f"adm_ucx_{a_id}", use_container_width=True):
                                try:
                                    api.undo_cancel({"appointment_id": a_id})
                                    st.session_state["admin_msg"] = f"Appointment restored for {name}"
                                    st.rerun()
                                except Exception as ex:
                                    st.error(f"{ex}")
                        elif a_status in ("completed", "checked_in", "in_progress"):
                            ac4.write(f"Slot #{a.get('slot_number', '—')}")
                        if a.get("notes") and a["notes"] != "None":
                            st.caption(f"📝 {a['notes']}")
            else:
                st.info("No appointments found for this patient.")

            # ── Admin actions bar ──
            st.divider()
            st.markdown("**⚙️ Admin Actions**")
            act1, act2, act3, act4 = st.columns(4)

            # Book appointment for this patient (or their beneficiary)
            with act1.popover("📅 Book Appointment", use_container_width=True):
                st.markdown(f"**Book Appointment**")

                # ── Who is this for? (self + beneficiaries) ──
                bk_for_options = [f"{name} (Self)"]
                bk_for_ids = {0: pid}  # index → patient_id to book for
                bk_rels = detail.get("relationships", [])
                for ri, rel in enumerate(bk_rels):
                    bname = rel.get("beneficiary_name", "?")
                    rtype = (rel.get("relationship_type") or "other").title()
                    bk_for_options.append(f"{bname} ({rtype})")
                    bk_for_ids[ri + 1] = rel.get("beneficiary_patient_id", pid)
                bk_for_idx = st.radio("Booking for", bk_for_options, key=f"bk_for_{pid}", horizontal=False)
                bk_for_sel = bk_for_options.index(bk_for_idx) if bk_for_idx in bk_for_options else 0
                bk_patient_id = bk_for_ids.get(bk_for_sel, pid)
                bk_patient_name = bk_for_idx.split(" (")[0]

                st.divider()

                # ── Department filter ──
                try:
                    bk_docs = api.list_doctors()
                except Exception:
                    bk_docs = []
                bk_depts = sorted(set(d.get("specialization", "") for d in bk_docs if d.get("specialization")))
                bk_dept = st.selectbox("Department", ["All"] + bk_depts, key=f"bk_dept_{pid}")
                if bk_dept != "All":
                    bk_docs = [d for d in bk_docs if d.get("specialization") == bk_dept]
                if not bk_docs:
                    st.warning("No doctors available.")
                else:
                    bk_doc_labels = [f"{d['full_name']} ({d['specialization']})" for d in bk_docs]
                    bk_doc_idx = st.selectbox("Doctor", range(len(bk_doc_labels)),
                                               format_func=lambda i: bk_doc_labels[i], key=f"bk_doc_{pid}")
                    bk_doc = bk_docs[bk_doc_idx]

                    # ── Date picker ──
                    from datetime import date as _bk_d
                    _bk_today = _bk_d.today()
                    bk_date = st.date_input("📅 Date", value=_bk_today, key=f"bk_date_{pid}")
                    bk_from, bk_to = bk_date, bk_date

                    # Load ALL sessions (active + inactive) for the date range
                    try:
                        bk_sessions = api.get_doctor_sessions(
                            bk_doc["doctor_id"],
                            from_date=str(bk_from),
                            to_date=str(bk_to),
                            include_all=True,
                        )
                        # Show active and inactive (staff can activate inactive)
                        bk_bookable = [s for s in bk_sessions if s.get("status") in ("active", "inactive")]
                    except Exception:
                        bk_bookable = []
                    if not bk_bookable:
                        st.info(f"No sessions found for {bk_doc['full_name']} in the selected date range. "
                                f"The doctor may not have sessions scheduled, or all sessions are completed/cancelled.")
                    else:
                        def _bk_sess_label(s):
                            tag = ""
                            if s.get("status") == "inactive":
                                tag = " ⚪ INACTIVE"
                            cap = s.get('available_capacity', '?')
                            return (f"{s['session_date']} • "
                                    f"{str(s.get('start_time', ''))[:5]}–{str(s.get('end_time', ''))[:5]} • "
                                    f"{cap} slots avail{tag}")

                        bk_sess_labels = [_bk_sess_label(s) for s in bk_bookable]
                        bk_sess_idx = st.selectbox("Session", range(len(bk_sess_labels)),
                                                    format_func=lambda i: bk_sess_labels[i], key=f"bk_sess_{pid}")
                        bk_sess = bk_bookable[bk_sess_idx]

                        if bk_sess.get("status") == "inactive":
                            st.warning("⚪ This session is **inactive**. You need to activate it first, or ask the doctor to activate it from their dashboard.")
                            if st.button("🟢 Activate & Continue", key=f"bk_activate_{pid}"):
                                try:
                                    api.activate_session({"session_id": bk_sess["session_id"]})
                                    st.success("Session activated!")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Failed: {e}")
                        else:
                            bk_total = bk_sess.get("total_slots", 1)
                            bk_dur = bk_sess.get("slot_duration_minutes", 15)
                            bk_start = str(bk_sess.get("start_time", "09:00"))
                            from datetime import datetime as _bk_dt
                            _bk_now_min = _bk_dt.now().hour * 60 + _bk_dt.now().minute
                            _bk_is_today = str(bk_date) == str(_bk_d.today())
                            bk_slot_opts = []  # list of (slot_number, label)
                            for si in range(1, bk_total + 1):
                                try:
                                    hh, mm = int(bk_start[:2]), int(bk_start[3:5])
                                    t_min = hh * 60 + mm + (si - 1) * bk_dur
                                    # Skip past slots for today
                                    if _bk_is_today and t_min + bk_dur <= _bk_now_min:
                                        continue
                                    t_str = f"{t_min // 60:02d}:{t_min % 60:02d}"
                                except Exception:
                                    t_str = f"Slot {si}"
                                bk_slot_opts.append((si, f"Slot {si} — {t_str}"))
                            if not bk_slot_opts:
                                st.warning("All time slots for this session have already passed.")
                            else:
                                bk_slot_idx = st.selectbox("Time Slot", range(len(bk_slot_opts)),
                                                            format_func=lambda i: bk_slot_opts[i][1], key=f"bk_slot_{pid}")
                                bk_slot_num = bk_slot_opts[bk_slot_idx][0]

                                st.caption(f"**Patient:** {bk_patient_name}  •  **Doctor:** {bk_doc['full_name']}  •  **Slot:** {bk_slot_opts[bk_slot_idx][1]}")

                                if st.button("✅ Confirm Booking", key=f"bk_confirm_{pid}", type="primary", use_container_width=True):
                                    try:
                                        result = api.staff_book({
                                            "session_id": bk_sess["session_id"],
                                            "patient_id": bk_patient_id,
                                            "slot_number": bk_slot_num,
                                        })
                                        st.session_state["admin_msg"] = f"Appointment booked for {bk_patient_name} with {bk_doc['full_name']}"
                                        st.rerun()
                                    except Exception as ex:
                                        st.error(f"Booking failed: {ex}")

            # Risk reset
            with act2.popover("🔧 Reset Risk", use_container_width=True):
                new_risk = st.number_input("New score", 0.0, 10.0, 0.0, step=0.5, key=f"rr_{pid}")
                if st.button("Reset Risk", key=f"rr_btn_{pid}", type="primary", use_container_width=True):
                    try:
                        api.admin_reset_risk(pid, new_risk)
                        st.session_state["admin_msg"] = f"Risk reset to {new_risk} for {name}"
                        st.rerun()
                    except Exception as e:
                        st.error(f"{e}")

            # Edit profile
            with act3.popover("✏️ Edit Profile", use_container_width=True):
                st.markdown("**Edit Patient Profile**")
                ep_name = st.text_input("Full Name", value=detail.get("full_name") or name or "", key=f"ep_fn_{pid}")
                ep_email = st.text_input("Email", value=detail.get("email") or "", key=f"ep_em_{pid}")
                ep_phone = st.text_input("Phone", value=detail.get("phone") or "", key=f"ep_ph_{pid}")
                _gender_opts = ["", "Male", "Female", "Other"]
                _cur_gender = detail.get("gender") or ""
                _gi = _gender_opts.index(_cur_gender) if _cur_gender in _gender_opts else 0
                ep_gender = st.selectbox("Gender", _gender_opts, index=_gi, key=f"ep_gn_{pid}")
                ep_blood = st.selectbox("Blood Group",
                                         ["", "A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"],
                                         index=["", "A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"].index(detail.get("blood_group") or ""),
                                         key=f"ep_bg_{pid}")
                ep_abha = st.text_input("ABHA/UHID", value=detail.get("abha_id") or "", key=f"ep_abha_{pid}")
                ep_addr = st.text_area("Address", value=detail.get("address") or "", key=f"ep_addr_{pid}")
                st.divider()
                st.markdown("**Emergency Contact**")
                ep_ec_name = st.text_input("Emergency Name", value=detail.get("emergency_contact_name") or "", key=f"ep_ecn_{pid}")
                ep_ec_phone = st.text_input("Emergency Phone", value=detail.get("emergency_contact_phone") or "", key=f"ep_ecp_{pid}")
                if st.button("💾 Save Changes", key=f"ep_save_{pid}", type="primary", use_container_width=True):
                    payload = {}
                    if ep_name and ep_name != (detail.get("full_name") or name or ""): payload["full_name"] = ep_name
                    if ep_email and ep_email != (detail.get("email") or ""): payload["email"] = ep_email
                    if ep_phone and ep_phone != (detail.get("phone") or ""): payload["phone"] = ep_phone
                    if ep_gender and ep_gender != (detail.get("gender") or ""): payload["gender"] = ep_gender
                    if ep_blood and ep_blood != (detail.get("blood_group") or ""): payload["blood_group"] = ep_blood
                    if ep_abha and ep_abha != (detail.get("abha_id") or ""): payload["abha_id"] = ep_abha
                    if ep_addr and ep_addr != (detail.get("address") or ""): payload["address"] = ep_addr
                    if ep_ec_name and ep_ec_name != (detail.get("emergency_contact_name") or ""): payload["emergency_contact_name"] = ep_ec_name
                    if ep_ec_phone and ep_ec_phone != (detail.get("emergency_contact_phone") or ""): payload["emergency_contact_phone"] = ep_ec_phone
                    if payload:
                        try:
                            api.admin_update_patient(pid, payload)
                            st.session_state["admin_msg"] = f"Profile updated for {ep_name or name}"
                            st.rerun()
                        except Exception as e:
                            st.error(f"{e}")
                    else:
                        st.info("No changes to save.")

            # Toggle active status
            is_active = detail.get("is_active") in ("True", "true", True)
            toggle_label = "🚫 Deactivate" if is_active else "✅ Reactivate"
            if act4.button(toggle_label, key=f"toggle_{pid}", use_container_width=True):
                try:
                    uid = detail.get("user_id", "")
                    if uid and uid != "None":
                        api.admin_toggle_user(uid)
                        status_word = "deactivated" if is_active else "reactivated"
                        st.session_state["admin_msg"] = f"Account {status_word} for {name}"
                        st.rerun()
                except Exception as e:
                    st.error(f"{e}")


def page_admin_sessions():
    """Session overview — all sessions across all doctors, with department & doctor filters."""
    tc1, tc2 = st.columns([6, 1])
    tc1.title("📅 Session Overview")
    if tc2.button("🔄 Refresh", key="refresh_admin_sess", use_container_width=True):
        st.rerun()

    # Load doctors for filter dropdowns
    try:
        all_docs = api.admin_list_doctors()
    except Exception:
        all_docs = []

    departments = sorted(set(d.get("specialization", "") for d in all_docs if d.get("specialization")))

    # Filters row
    fc1, fc2, fc3, fc4 = st.columns(4)
    from datetime import date as _date_cls
    filter_date = fc1.date_input("Date", value=_date_cls.today(), key="admin_sess_date")
    filter_dept = fc2.selectbox("Department", ["All"] + departments, key="admin_sess_dept")
    # Doctor dropdown — filtered by department
    if filter_dept != "All":
        dept_docs = [d for d in all_docs if d.get("specialization") == filter_dept]
    else:
        dept_docs = all_docs
    doc_names = ["All"] + [d["full_name"] for d in dept_docs]
    filter_doc = fc3.selectbox("Doctor", doc_names, key="admin_sess_doc")
    filter_status = fc4.selectbox("Status", ["all", "active", "inactive", "completed", "cancelled"],
                                   key="admin_sess_status")

    # Resolve doctor_id
    sel_doc_id = ""
    if filter_doc != "All":
        match = [d for d in dept_docs if d["full_name"] == filter_doc]
        if match:
            sel_doc_id = str(match[0]["doctor_id"])

    try:
        sessions = api.admin_list_sessions(
            date_str=str(filter_date),
            status="" if filter_status == "all" else filter_status,
            specialization="" if filter_dept == "All" else filter_dept,
            doctor_id=sel_doc_id,
        )
    except Exception as e:
        st.error(f"Failed: {e}")
        return

    if not sessions:
        st.info("No sessions found.")
        return

    st.caption(f"{len(sessions)} sessions")

    # Group by department → doctor
    by_dept = {}
    for s in sessions:
        dept = s.get("specialization", "Other")
        if dept not in by_dept:
            by_dept[dept] = {}
        doc = s.get("doctor_name", "Unknown")
        if doc not in by_dept[dept]:
            by_dept[dept][doc] = []
        by_dept[dept][doc].append(s)

    for dept in sorted(by_dept.keys()):
        st.subheader(f"🏥 {dept}")
        for doc_name, doc_sessions in sorted(by_dept[dept].items()):
            with st.expander(f"🩺 {doc_name} ({len(doc_sessions)} sessions)", expanded=True):
                for s in doc_sessions:
                    status = s.get("status", "—")
                    si = {"active": "🟢", "inactive": "🟡", "completed": "✅", "cancelled": "❌"}.get(status, "•")
                    start = str(s.get("start_time", ""))[:5]
                    end = str(s.get("end_time", ""))[:5]
                    booked = s.get("booked_count", "0")
                    total = s.get("total_slots", "0")
                    delay = s.get("delay_minutes", "0")

                    col1,col2,col3 = st.columns(3)
                    session_id = s.get("session_id") or s.get("id")
                    status_norm=str(status).lower()

                    # st.caption(f"Session ID: {session_id}  •  Status: {status_norm}")

                    # st.write(f"🔍 session_id type: {type(session_id)} | value: {repr(session_id)}")
                    # st.write(f"🔍 status type: {type(status)} | value: {repr(status)}")
                    # st.write(f"🔍 status_norm type: {type(status_norm)} | value: {repr(status_norm)}")

                    



                    with col1:
                        if status_norm=='active':
                            if st.button("🟢 DeActivate", key=f"activate_{session_id}", use_container_width=True):
                                try:
                                    api.deactivate_session({"session_id": session_id})
                                    st.session_state["admin_msg"] = f"Session {session_id} deactivated"
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"{e}")

                        elif status_norm=='inactive':
                            if st.button("🔄 Activate", key=f"deactivate_{session_id}", use_container_width=True):
                                try:
                                    api.activate_session({"session_id": session_id})
                                    st.session_state["admin_msg"] = f"Session {session_id} activated"
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"{e}")
                        else:
                            st.write(f"Status: {status_norm.title()}")

                    # st.caption(f"Debug session_id: {session_id}")

                    

                    

                    detail = f"{booked}/{total} booked"
                    if str(delay) != "0":
                        detail += f"  |  ⏰ {delay}min delay"

                    st.markdown(
                        f'<div style="background:#fff;border:1px solid #d1d5db;border-radius:8px;'
                        f'padding:10px 14px;margin-bottom:6px;color:#1e293b">'
                        f'{si} <strong>{start} – {end}</strong>  •  {detail}'
                        f'<span style="float:right;color:#6b7280;font-size:0.85em">{status.title()}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    if s.get("notes") and s["notes"] != "None":
                        st.caption(f"📝 {s['notes']}")


def page_admin_audit():
    """Audit log viewer — all system actions."""
    tc1, tc2 = st.columns([6, 1])
    tc1.title("📜 Audit Logs")
    if tc2.button("🔄 Refresh", key="refresh_admin_audit", use_container_width=True):
        st.rerun()

    # Filters
    fc1, fc2, fc3 = st.columns(3)
    action_filter = fc1.selectbox(
        "Action",
        ["all", "BOOKED", "CANCELLED", "SESSION_CANCELLED", "WAITLISTED",
         "check_in", "complete_session", "activate_session", "deactivate_session",
         "reschedule", "escalate_priority"],
        key="audit_action",
    )
    from datetime import date as _date_cls
    from_date = fc2.date_input("From", value=_date_cls.today(), key="audit_from")
    to_date = fc3.date_input("To", value=_date_cls.today(), key="audit_to")

    try:
        result = api.admin_get_audit(
            action="" if action_filter == "all" else action_filter,
            from_date=str(from_date),
            to_date=str(to_date),
        )
    except Exception as e:
        st.error(f"Failed: {e}")
        return

    logs = result.get("logs", [])
    total = result.get("total", 0)

    st.caption(f"Showing {len(logs)} of {total} log entries")

    if not logs:
        st.info("No audit entries for the selected filters.")
        return

    for log in logs:
        action = log.get("action", "—")
        action_icons = {
            "BOOKED": "📅", "CANCELLED": "❌", "SESSION_CANCELLED": "🚫",
            "WAITLISTED": "📋", "check_in": "✅", "complete_session": "✔️",
            "activate_session": "🟢", "deactivate_session": "🔴",
            "reschedule": "🔄", "escalate_priority": "⚡",
        }
        icon = action_icons.get(action, "•")
        ts = str(log.get("created_at", ""))[:19]
        performer = log.get("performed_by_name") or "System"
        patient = log.get("patient_name") or "—"
        meta = log.get("metadata") or {}

        with st.container(border=True):
            lc1, lc2 = st.columns([4, 1])
            lc1.markdown(f"{icon} **{action.replace('_', ' ').title()}** — Patient: **{patient}**")
            lc1.caption(f"By: {performer}  •  {ts}")
            if meta:
                meta_str = ", ".join(f"{k}: {v}" for k, v in meta.items() if k not in ("ip_address",))
                if meta_str:
                    lc1.caption(f"Details: {meta_str}")
            lc2.caption(action)


def page_admin_cancel():
    tc1, tc2 = st.columns([6, 1])
    tc1.title("❌ Cancel Entire Session")
    if tc2.button("🔄 Refresh", key="refresh_admin_cancel", use_container_width=True):
        st.rerun()
    st.error("This cancels ALL appointments. No penalties applied to patients.")

    session_id = _smart_session_picker("cancel_sp")
    if not session_id:
        return

    try:
        q = api.get_queue(session_id)
        st.write(f"**Doctor:** {q.get('doctor_name', '—')}  •  **Patients affected:** {q.get('total_in_queue', 0)}")
    except Exception:
        pass

    reason = st.text_area("Cancellation reason")
    if st.button("❌ Cancel This Session", type="primary", use_container_width=True):
        if not reason or len(reason) < 5:
            st.error("Reason must be at least 5 characters.")
        else:
            try:
                r = api.cancel_session({"session_id": session_id, "reason": reason})
                st.success(r["message"])
                st.write(f"Appointments cancelled: {r['appointments_cancelled']}")
                st.write(f"Waitlist cancelled: {r['waitlist_cancelled']}")
                st.session_state.pop("today_sessions", None)
            except Exception as e:
                st.error(f"Failed: {e}")


# ════════════════════════════════════════════════════════════
# AI CHATBOT
# ════════════════════════════════════════════════════════════

def page_chatbot():
    """AI Chatbot — clean two-mode interface."""
    st.title("🤖 AI Assistant")

    user = st.session_state.user
    role = user["role"]

    # ── Check if chatbot is configured ──
    try:
        health = api.chat_health()
        if health.get("status") != "ready":
            st.warning("AI Chatbot is not configured. Ask your administrator to set the OPENAI_API_KEY.")
            return
    except Exception:
        st.warning("Could not reach chatbot service. Make sure the backend is running.")
        return

    # ── Init session state for chat ──
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []
    if "chat_form_done" not in st.session_state:
        st.session_state.chat_form_done = False
    if "chat_patient_context" not in st.session_state:
        st.session_state.chat_patient_context = ""
    if "chat_mode" not in st.session_state:
        st.session_state.chat_mode = ""  # "", "book", "chat"

    # ── Restore chat history from server on fresh page load ──
    if not st.session_state.chat_messages and "chat_history_loaded" not in st.session_state:
        st.session_state.chat_history_loaded = True
        try:
            server_history = api.chat_history()
            if server_history:
                st.session_state.chat_messages = server_history
                st.session_state.chat_form_done = True
                st.session_state.chat_mode = "chat"
        except Exception:
            pass

    # ── MODE SELECTION (nurse/admin only) ──
    if role in ("nurse", "admin") and st.session_state.chat_mode == "":
        _show_mode_selection(role)
        return

    # ── BOOKING FORM (nurse/admin chose "book") ──
    if st.session_state.chat_mode == "book" and not st.session_state.chat_form_done:
        if role == "nurse":
            _show_nurse_intake_form()
        elif role == "admin":
            _show_admin_intake_form()
        return

    # ── For patient/doctor: skip mode selection, go straight to chat ──
    if role in ("patient", "doctor") and not st.session_state.chat_form_done:
        # Auto-mark as done — they go straight to chat
        st.session_state.chat_form_done = True
        st.session_state.chat_mode = "chat"
        greeting = f"Hello {user['full_name']}! I'm your AI assistant. How can I help you today?"
        st.session_state.chat_messages = [{"role": "assistant", "content": greeting}]
        st.rerun()
        return

    # ── Chat interface ──
    _show_chat_interface()


def _show_mode_selection(role: str):
    """Show two clean buttons: Book Patient or Just Chat."""
    user = st.session_state.user
    st.markdown(f"**Welcome, {user['full_name']}!** ({role.title()})")
    st.markdown("---")
    st.markdown("#### What would you like to do?")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(
            '<div style="background:#e8f5e9;border-radius:12px;padding:20px;text-align:center;">'
            '<h3 style="margin:0;">📋 Book a Patient</h3>'
            '<p style="color:#555;margin:8px 0 0;">Fill the patient form first,<br>then chat to complete the booking</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        if st.button("📋 Book a Patient", use_container_width=True, key="mode_book"):
            st.session_state.chat_mode = "book"
            st.rerun()
    with col2:
        st.markdown(
            '<div style="background:#e3f2fd;border-radius:12px;padding:20px;text-align:center;">'
            '<h3 style="margin:0;">💬 Just Chat</h3>'
            '<p style="color:#555;margin:8px 0 0;">View ops board, manage queue,<br>check-in, reassign, sessions, etc.</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        if st.button("💬 Just Chat", use_container_width=True, key="mode_chat"):
            st.session_state.chat_mode = "chat"
            st.session_state.chat_form_done = True
            greeting = f"Hello {user['full_name']}! I'm your AI assistant. How can I help you today?"
            st.session_state.chat_messages = [{"role": "assistant", "content": greeting}]
            st.rerun()


def _get_dept_list():
    """Helper: fetch departments for dropdowns."""
    try:
        depts = api.list_departments()
        if isinstance(depts, list) and depts:
            if isinstance(depts[0], dict):
                return [d.get("specialization", d.get("name", "")) for d in depts]
            return depts
    except Exception:
        pass
    return []



def _show_nurse_intake_form():
    """Nurse intake: collect patient details for booking. Clean and focused."""
    st.markdown("### 📋 Patient Booking Form")
    if st.button("← Back", key="nurse_form_back"):
        st.session_state.chat_mode = ""
        st.rerun()

    st.caption("Fill in the patient details. The AI will use this data to book directly.")
    user = st.session_state.user
    departments = _get_dept_list()

    with st.form("nurse_intake_form"):
        pc1, pc2 = st.columns(2)
        with pc1:
            pat_name = st.text_input("Patient Full Name *", placeholder="e.g. Simha Kumar")
            pat_phone = st.text_input("Phone Number *", placeholder="e.g. 9876543210")
            pat_uhid = st.text_input("UHID / ABHA ID", placeholder="e.g. 14-digit ABHA number")
            pat_gender = st.selectbox("Gender", ["male", "female", "other"])
        with pc2:
            pat_dob = st.date_input("Date of Birth", value=None, min_value=__import__("datetime").date(1920, 1, 1))
            pat_blood = st.selectbox("Blood Group", ["", "A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"])
            preferred_dept = st.selectbox("Department *", ["Not sure"] + departments)
            urgency = st.selectbox("Urgency", ["routine", "soon", "urgent"])

        symptoms = st.text_area("Symptoms / Reason for Visit",
                                 placeholder="e.g. Chest pain since morning, mild fever...",
                                 height=80)
        additional = st.text_input("Additional Notes (optional)",
                                    placeholder="e.g. Allergic to aspirin, needs wheelchair access...")

        is_walkin = st.checkbox("New walk-in patient (not yet registered)")
        is_emergency = st.checkbox("Emergency booking")

        submitted = st.form_submit_button("🚀 Enter Chat & Book", use_container_width=True, type="primary")

    if submitted:
        if not pat_name or len(pat_name.strip()) < 2:
            st.error("Patient name is required.")
            return

        # Determine task from checkboxes
        if is_emergency:
            task = "Emergency booking"
        elif is_walkin:
            task = "Register new walk-in patient and book"
        else:
            task = "Book appointment for existing patient"

        dept_text = preferred_dept if preferred_dept != "Not sure" else "not specified"
        ctx_parts = [f"Staff (Nurse): {user['full_name']}", f"Task: {task}"]
        ctx_parts.append(f"Patient Name: {pat_name.strip()}")
        if pat_phone:
            ctx_parts.append(f"Patient Phone: {pat_phone.strip()}")
        if pat_uhid:
            ctx_parts.append(f"Patient UHID/ABHA: {pat_uhid.strip()}")
        ctx_parts.append(f"Patient Gender: {pat_gender}")
        if pat_dob:
            ctx_parts.append(f"Patient DOB: {str(pat_dob)}")
        if pat_blood:
            ctx_parts.append(f"Blood Group: {pat_blood}")
        if dept_text != "not specified":
            ctx_parts.append(f"Preferred Department: {dept_text}")
        ctx_parts.append(f"Urgency: {urgency}")
        if symptoms:
            ctx_parts.append(f"Symptoms: {symptoms.strip()}")
        if additional:
            ctx_parts.append(f"Notes: {additional.strip()}")
        st.session_state.chat_patient_context = "\n".join(ctx_parts)
        st.session_state.chat_form_done = True

        # Compact greeting
        greeting = f"Hello {user['full_name']}! I have the patient details.\n\n"
        greeting += f"**{task}**\n"
        greeting += f"**Patient:** {pat_name.strip()}"
        if pat_phone:
            greeting += f" | {pat_phone.strip()}"
        greeting += f"\n**Dept:** {dept_text} | **Urgency:** {urgency}\n\n"
        greeting += "I'll start looking for available doctors and slots now. Say **proceed** or tell me what to do."

        st.session_state.chat_messages = [{"role": "assistant", "content": greeting}]
        st.rerun()


def _show_admin_intake_form():
    """Admin intake: patient details for booking. Same form as nurse."""
    st.markdown("### 📋 Patient Booking Form (Admin)")
    if st.button("← Back", key="admin_form_back"):
        st.session_state.chat_mode = ""
        st.rerun()

    st.caption("Fill in the patient details. The AI will use this data to book directly.")
    user = st.session_state.user
    departments = _get_dept_list()

    with st.form("admin_intake_form"):
        ac1, ac2 = st.columns(2)
        with ac1:
            pat_name = st.text_input("Patient Name *", placeholder="e.g. Ravi Kumar", key="admin_pat_name")
            pat_phone = st.text_input("Phone *", placeholder="e.g. 9876543210", key="admin_pat_phone")
            pat_uhid = st.text_input("UHID / ABHA ID", placeholder="e.g. 14-digit ABHA", key="admin_pat_uhid")
            pat_gender = st.selectbox("Gender", ["male", "female", "other"], key="admin_pat_gender")
        with ac2:
            pat_dob = st.date_input("Date of Birth", value=None, min_value=__import__("datetime").date(1920, 1, 1), key="admin_pat_dob")
            pat_blood = st.selectbox("Blood Group", ["", "A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"], key="admin_pat_blood")
            preferred_dept = st.selectbox("Department *", ["Not sure"] + departments, key="admin_dept")
            urgency = st.selectbox("Urgency", ["routine", "soon", "urgent"], key="admin_urgency")

        symptoms = st.text_area("Symptoms / Reason for Visit", placeholder="e.g. Fever, headache...", height=80, key="admin_symptoms")

        is_walkin = st.checkbox("New walk-in patient (not yet registered)", key="admin_walkin")
        is_emergency = st.checkbox("Emergency booking", key="admin_emergency")

        submitted = st.form_submit_button("🚀 Enter Chat & Book", use_container_width=True, type="primary")

    if submitted:
        if not pat_name or len(pat_name.strip()) < 2:
            st.error("Patient name is required.")
            return

        if is_emergency:
            task = "Emergency booking"
        elif is_walkin:
            task = "Register new walk-in patient and book"
        else:
            task = "Book appointment for existing patient"

        dept_text = preferred_dept if preferred_dept != "Not sure" else "not specified"
        ctx_parts = [f"Admin: {user['full_name']}", f"Task: {task}"]
        ctx_parts.append(f"Patient Name: {pat_name.strip()}")
        if pat_phone:
            ctx_parts.append(f"Patient Phone: {pat_phone.strip()}")
        if pat_uhid:
            ctx_parts.append(f"Patient UHID/ABHA: {pat_uhid.strip()}")
        ctx_parts.append(f"Patient Gender: {pat_gender}")
        if pat_dob:
            ctx_parts.append(f"Patient DOB: {str(pat_dob)}")
        if pat_blood:
            ctx_parts.append(f"Blood Group: {pat_blood}")
        if dept_text != "not specified":
            ctx_parts.append(f"Preferred Department: {dept_text}")
        ctx_parts.append(f"Urgency: {urgency}")
        if symptoms:
            ctx_parts.append(f"Symptoms: {symptoms.strip()}")
        st.session_state.chat_patient_context = "\n".join(ctx_parts)
        st.session_state.chat_form_done = True

        greeting = f"Hello {user['full_name']}! I have the patient details.\n\n"
        greeting += f"**{task}**\n"
        greeting += f"**Patient:** {pat_name.strip()}"
        if pat_phone:
            greeting += f" | {pat_phone.strip()}"
        greeting += f"\n**Dept:** {dept_text} | **Urgency:** {urgency}\n\n"
        greeting += "I'll start looking for available doctors and slots now. Say **proceed** or tell me what to do."

        st.session_state.chat_messages = [{"role": "assistant", "content": greeting}]
        st.rerun()


def _autoplay_audio(audio_bytes: bytes):
    """Queue TTS audio for playback after next rerun (survives st.rerun cycle)."""
    st.session_state._pending_tts_audio = audio_bytes


def _clean_text_for_tts(text: str) -> str:
    """Strip markdown formatting, code blocks, and special chars for natural TTS."""
    import re
    # Remove code blocks (```...```)
    text = re.sub(r'```[\s\S]*?```', ' code block omitted ', text)
    # Remove inline code (`...`)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # Remove markdown bold/italic (**text**, *text*, __text__, _text_)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'_(.+?)_', r'\1', text)
    # Remove markdown headers (# ## ###)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Remove markdown links [text](url) → text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Remove bullet points (- or *)
    text = re.sub(r'^\s*[-*]\s+', '', text, flags=re.MULTILINE)
    # Remove numbered lists (1. 2. etc)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    # Remove emoji (common unicode ranges)
    text = re.sub(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F900-\U0001F9FF\U00002702-\U000027B0\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF]', '', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _send_and_reply(prompt: str, speak: bool = False):
    """Send a message to the chatbot, display the reply, and optionally speak it."""
    st.session_state.chat_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                # Only send patient_context on the FIRST message (server stores it)
                ctx = ""
                if not st.session_state.get("chat_context_sent"):
                    ctx = st.session_state.chat_patient_context
                    st.session_state.chat_context_sent = True

                response = api.chat_send_message(
                    message=prompt,
                    patient_context=ctx,
                )
                reply = response.get("reply", "Sorry, I couldn't process that.")
            except Exception as e:
                reply = f"Error communicating with AI: {e}"

            st.markdown(reply)
            st.session_state.chat_messages.append({"role": "assistant", "content": reply})

        # Text-to-Speech: convert reply to audio and auto-play
        if speak and reply and not reply.startswith("Error"):
            try:
                tts_text = _clean_text_for_tts(reply)
                if tts_text:
                    voice = st.session_state.get("tts_voice", "alloy")
                    with st.spinner("🔊 Speaking..."):
                        tts_audio = api.chat_tts(tts_text, voice=voice)
                        _autoplay_audio(tts_audio)
            except Exception as e:
                st.caption(f"⚠️ Voice playback unavailable")


def _show_chat_interface():
    """Chat interface with text input, mic button, and TTS auto-play."""
    user = st.session_state.user
    role = user["role"]

    # Init voice mode toggle
    if "voice_mode" not in st.session_state:
        st.session_state.voice_mode = False
    if "tts_voice" not in st.session_state:
        st.session_state.tts_voice = "alloy"

    # Toolbar
    col1, col2, col3, col4 = st.columns([5, 1.5, 1.5, 2])
    with col1:
        mode_label = "Booking" if st.session_state.chat_mode == "book" else "Chat"
        st.caption(f"Chatting as **{user['full_name']}** ({role.upper()}) — {mode_label} mode")
    with col2:
        # Voice mode toggle
        if HAS_AUDIO_RECORDER:
            voice_label = "🔊 Voice On" if st.session_state.voice_mode else "🔇 Voice Off"
            if st.button(voice_label, use_container_width=True, key="toggle_voice"):
                st.session_state.voice_mode = not st.session_state.voice_mode
                st.rerun()
    with col3:
        if st.button("🔄 New Chat", use_container_width=True):
            try:
                api.chat_clear()
            except Exception:
                pass
            st.session_state.chat_messages = []
            st.session_state.chat_form_done = False
            st.session_state.chat_patient_context = ""
            st.session_state.chat_mode = ""
            st.session_state.chat_context_sent = False
            st.session_state.voice_mode = False
            st.session_state.pop("chat_history_loaded", None)
            st.rerun()
    with col4:
        if st.session_state.chat_mode == "book" and role in ("nurse", "admin"):
            if st.button("📋 Edit Form", use_container_width=True):
                st.session_state.chat_form_done = False
                st.rerun()

    # ── Voice settings in sidebar when voice mode is on ──
    if st.session_state.voice_mode:
        with st.sidebar:
            st.markdown("#### 🔊 Voice Settings")
            _voices = {"Alloy (neutral)": "alloy", "Echo (male)": "echo", "Fable (British)": "fable",
                        "Onyx (deep male)": "onyx", "Nova (female)": "nova", "Shimmer (soft female)": "shimmer"}
            _voice_labels = list(_voices.keys())
            _current_voice = st.session_state.get("tts_voice", "alloy")
            _current_idx = list(_voices.values()).index(_current_voice) if _current_voice in _voices.values() else 0
            _selected = st.selectbox("Voice", _voice_labels, index=_current_idx, key="voice_select")
            st.session_state.tts_voice = _voices[_selected]

    st.divider()

    # Display message history (local UI copy)
    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # ── Play queued TTS audio (survives st.rerun cycle) ──
    if "_pending_tts_audio" in st.session_state and st.session_state._pending_tts_audio:
        _tts_bytes = st.session_state.pop("_pending_tts_audio")
        st.audio(_tts_bytes, format="audio/mpeg", autoplay=True)

    # ── Mic input (voice mode) ──
    if HAS_AUDIO_RECORDER and st.session_state.voice_mode:
        st.markdown("**🎙️ Tap the mic to speak, tap again to stop:**")
        audio_bytes = audio_recorder(
            text="",
            recording_color="#e74c3c",
            neutral_color="#3498db",
            icon_size="2x",
            pause_threshold=2.0,
            key="voice_recorder",
        )
        if audio_bytes and len(audio_bytes) > 100:
            # Avoid re-processing the same audio on Streamlit reruns
            import hashlib
            audio_hash = hashlib.md5(audio_bytes).hexdigest()
            if audio_hash != st.session_state.get("_last_audio_hash"):
                st.session_state._last_audio_hash = audio_hash
                # Detect format from header bytes
                if audio_bytes[:4] == b'RIFF':
                    _fname = "voice.wav"
                elif audio_bytes[:3] == b'ID3' or audio_bytes[:2] == b'\xff\xfb':
                    _fname = "voice.mp3"
                elif audio_bytes[:4] == b'OggS':
                    _fname = "voice.ogg"
                else:
                    _fname = "voice.webm"  # audio_recorder default
                with st.spinner("🎙️ Transcribing..."):
                    try:
                        result = api.chat_transcribe(audio_bytes, filename=_fname)
                        transcribed_text = result.get("text", "").strip()
                    except Exception as e:
                        st.error(f"Could not transcribe audio: {e}")
                        transcribed_text = ""

                if transcribed_text:
                    st.caption(f"🗣️ *\"{transcribed_text}\"*")
                    _send_and_reply(transcribed_text, speak=True)
                    st.rerun()

    # ── Text input (always available) ──
    if prompt := st.chat_input("Type your message..."):
        _send_and_reply(prompt, speak=st.session_state.voice_mode)
        st.rerun()


# ════════════════════════════════════════════════════════════
# DASHBOARD ROUTER
# ════════════════════════════════════════════════════════════

def page_dashboard():
    role = st.session_state.user["role"]
    if role == "patient":
        page_patient_dashboard()
    elif role == "doctor":
        page_doctor_dashboard()
    elif role == "admin":
        page_admin_dashboard()
    elif role == "nurse":
        page_staff_session()


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
    "nurse_patients": page_nurse_patients,
    "admin_home": page_admin_dashboard,
    "admin_users": page_admin_users,
    "admin_doctors": page_admin_doctors,
    "admin_sessions_overview": page_admin_sessions,
    "admin_patients": page_admin_patients,
    "admin_config": page_admin_config,
    "admin_audit": page_admin_audit,
    "admin_cancel": page_admin_cancel,
    "chatbot": page_chatbot,
}


def _handle_google_callback():
    """Check URL query params for Google OAuth callback tokens or errors."""
    params = st.query_params

    # Handle Google login error (user not registered)
    if params.get("google_login_error"):
        st.session_state["_google_error"] = params["google_login_error"]
        st.query_params.clear()
        return

    # Handle successful Google login
    if params.get("google_login") == "1" and params.get("access_token"):
        st.session_state.access_token = params["access_token"]
        st.session_state.refresh_token = params.get("refresh_token")
        try:
            me = api.get_me()
            st.session_state.user = me["user"]
            st.session_state.patient = me.get("patient")
            st.session_state.page = "dashboard"
        except Exception:
            st.session_state.access_token = None
            st.session_state.refresh_token = None
        st.query_params.clear()


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
