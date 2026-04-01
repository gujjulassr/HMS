"""Doctor-facing pages: dashboard, queue, and session controls."""
import streamlit as st
from streamlit_pages import api_client as api
from streamlit_pages.helpers import (_db_get_all_sessions_for_doctor, _fetch_all_doctors, 
                                     _mark_noshow, _calc_and_update_delay, _smart_session_picker, 
                                     _time_to_minutes_safe, _status_badge, _calc_slot_time)

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


