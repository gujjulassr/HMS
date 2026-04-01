"""Patient-facing pages: dashboard, booking, appointments, and profile."""
import streamlit as st
from streamlit_pages import api_client as api
from streamlit_pages.helpers import _fetch_all_doctors, _fetch_sessions_for_doctor, _calc_slot_time, _status_badge


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
