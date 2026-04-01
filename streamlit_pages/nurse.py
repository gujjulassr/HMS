"""Nurse-facing pages: session & queue management, patient lookup, emergency booking."""
import streamlit as st
from streamlit_pages import api_client as api
from streamlit_pages.helpers import (_smart_session_picker, _status_badge, _calc_and_update_delay,
                                     _mark_noshow, _time_to_minutes_safe, _calc_slot_time,
                                     _fetch_all_doctors)

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
                    nbk_date = st.date_input("📅 Date", value=_nbk_today, min_value=_nbk_today, key=f"nbk_date_{pid}")
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

