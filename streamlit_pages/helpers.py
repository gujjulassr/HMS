"""Shared helpers for all dashboard pages."""
import streamlit as st
from streamlit_pages import api_client as api
from datetime import date, datetime, timedelta


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
    try:
        sh, sm = int(s_start[:2]), int(s_start[3:5])
        # The completed slot was supposed to end at:
        slot_end_min = sh * 60 + sm + completed_slot * dur
        now = datetime.now()
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
