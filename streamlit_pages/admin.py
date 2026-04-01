"""Admin-facing pages — simplified, powerful interface.

Pages:
  1. Dashboard  — KPI stats + system config
  2. Staff      — All staff (doctors/nurses/admins): create, edit, toggle, doctor settings
  3. Patients   — Search, view, edit, family, risk, appointments
  4. Sessions   — Session overview + cancel + live queue (merged)
  5. Audit Logs — Action log viewer
"""
import streamlit as st
from streamlit_pages import api_client as api


# ════════════════════════════════════════════════════════════
# 1. DASHBOARD  (stats + config)
# ════════════════════════════════════════════════════════════

def page_admin_dashboard():
    """Admin overview — today's stats + system config."""
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

    k1.metric("Sessions Today", sess.get("total", 0), f"{sess.get('active', 0)} active")
    k2.metric("Appointments", appt.get("total", 0), f"{appt.get('completed', 0)} done")
    k3.metric("Doctors in Session", stats.get("active_doctors_today", 0),
              help="Doctors with an active session running today")
    k4.metric("High-Risk Patients", stats.get("high_risk_patients", 0))

    st.divider()

    # ── Sessions + Appointments side by side ──
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("#### Sessions")
        for key in ["active", "inactive", "completed", "cancelled"]:
            val = sess.get(key, 0)
            icons = {"active": "🟢", "inactive": "🟡", "completed": "✅", "cancelled": "❌"}
            st.write(f"{icons.get(key, '•')} **{key.title()}**: {val}")

    with c2:
        st.markdown("#### Appointments")
        for key in ["booked", "checked_in", "in_progress", "completed", "no_show", "cancelled", "emergencies"]:
            val = appt.get(key, 0)
            icons = {"booked": "📅", "checked_in": "✅", "in_progress": "🔄",
                     "completed": "✔️", "no_show": "⚠️", "cancelled": "❌", "emergencies": "🚨"}
            st.write(f"{icons.get(key, '•')} **{key.replace('_', ' ').title()}**: {val}")

    with c3:
        st.markdown("#### Users")
        st.write(f"**Total**: {users.get('total', 0)}")
        st.write(f"**Patients**: {users.get('patients', 0)}")
        st.write(f"**Doctors**: {users.get('doctors', 0)}")
        st.write(f"**Nurses**: {users.get('nurses', 0)}")
        st.write(f"**Admins**: {users.get('admins', 0)}")
        if users.get("deactivated", 0) > 0:
            st.write(f"⚠️ {users['deactivated']} deactivated")

    # ── System Config (collapsible) — admin only ──
    if st.session_state.get("user", {}).get("role") == "admin":
        st.divider()
        with st.expander("⚙️ System Configuration", expanded=False):
            _show_config_section()


def _show_config_section():
    """Inline config editor — replaces the old standalone config page."""
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

        cc1, cc2 = st.columns([4, 1])
        cc1.markdown(f"**{key}** = `{val}`")
        if desc:
            cc1.caption(f"{desc}  •  Updated: {updated}")

        with cc2.popover("✏️ Edit"):
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


# ════════════════════════════════════════════════════════════
# 2. STAFF MANAGEMENT  (merged Users + Doctors)
# ════════════════════════════════════════════════════════════

def page_admin_staff():
    """Unified staff management — doctors, nurses, admins. Create, edit, toggle."""
    tc1, tc2 = st.columns([6, 1])
    tc1.title("👥 Staff Management")
    if tc2.button("🔄 Refresh", key="refresh_admin_staff", use_container_width=True):
        st.rerun()

    if st.session_state.get("admin_msg"):
        st.success(st.session_state.pop("admin_msg"))

    tab_docs, tab_nurses, tab_create = st.tabs(["🩺 Doctors", "💉 Nurses & Admins", "➕ Add Staff"])

    # ── TAB 1: Doctors (with inline settings) ──
    with tab_docs:
        _show_doctors_tab()

    # ── TAB 2: Nurses & Admins ──
    with tab_nurses:
        _show_nurses_admins_tab()

    # ── TAB 3: Create staff ──
    with tab_create:
        _show_create_staff_form()


def _show_doctor_schedule(doctor_id: str, doctor_name: str, is_available: bool):
    """Show a calendar date picker + sessions for the selected date."""
    from datetime import date as _sch_d

    st.divider()
    cal1, cal2 = st.columns([1, 2])
    sel_date = cal1.date_input("📅 View Schedule", value=_sch_d.today(), key=f"doc_cal_{doctor_id}")

    try:
        day_sessions = api.get_doctor_sessions(
            doctor_id,
            from_date=str(sel_date),
            to_date=str(sel_date),
            include_all=True,
        )
    except Exception:
        day_sessions = []

    with cal2:
        if not day_sessions:
            if not is_available:
                st.error(f"🔴 No sessions — Doctor is **unavailable**")
            else:
                st.info(f"No sessions on {sel_date.strftime('%b %d, %Y')}")
        else:
            for s in day_sessions:
                s_status = str(s.get("status", "")).lower()
                s_icon = {"active": "🟢", "inactive": "🟡", "completed": "✅", "cancelled": "❌"}.get(s_status, "•")
                s_start = str(s.get("start_time", ""))[:5]
                s_end = str(s.get("end_time", ""))[:5]
                s_booked = s.get("booked_count", 0)
                s_total = s.get("total_slots", 0)
                s_cap = s.get("available_capacity", "?")
                st.write(f"{s_icon} **{s_start}–{s_end}** — {s_booked}/{s_total} booked, {s_cap} available — _{s_status.title()}_")


def _show_doctors_tab():
    """Doctor cards with expandable settings — replaces separate Doctors + Config pages."""
    try:
        depts = ["All"] + api.admin_list_departments()
    except Exception:
        depts = ["All"]
    dept_sel = st.selectbox("Filter by Department", depts, key="staff_doc_dept")

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

    for doc in doctors:
        did = str(doc["doctor_id"])
        avail = str(doc.get("is_available", "True")).lower() == "true"
        user_active = str(doc.get("user_active", "True")).lower() == "true"
        inactive_tag = "" if user_active else " • 🚫 Deactivated"

        try:
            fee_val = int(float(doc.get("consultation_fee", 500)))
        except (ValueError, TypeError):
            fee_val = 500
        try:
            max_val = int(doc.get("max_patients_per_slot", 2))
        except (ValueError, TypeError):
            max_val = 2

        status_icon = "🟢" if avail else "🔴"
        spec = doc.get("specialization") or "—"

        with st.expander(
            f"{status_icon} **{doc['full_name']}** — {spec} • ₹{fee_val}{inactive_tag}",
            expanded=False,
        ):
            # ── Info row ──
            i1, i2 = st.columns(2)
            i1.write(f"**Email:** {doc.get('email') or '—'}")
            i1.write(f"**Phone:** {doc.get('phone') or '—'}")
            i1.write(f"**Qualification:** {doc.get('qualification') or '—'}")
            i2.write(f"**License:** {doc.get('license_number') or '—'}")
            i2.write(f"**Fee:** ₹{fee_val}")
            i2.write(f"**Max Patients/Slot:** {max_val}")

            # ── Weekly Schedule (calendar view) ──
            _show_doctor_schedule(did, doc["full_name"], avail)

            # ── Actions row ──
            st.divider()
            a1, a2, a3 = st.columns(3)

            # Toggle availability
            avail_label = "Set Unavailable" if avail else "Set Available"
            if a1.button(avail_label, key=f"avail_{did}", use_container_width=True):
                try:
                    api.admin_update_doctor(did, {"is_available": not avail})
                    st.session_state["admin_msg"] = f"{'Disabled' if avail else 'Enabled'} {doc['full_name']}"
                    st.rerun()
                except Exception as e:
                    st.error(f"{e}")

            # Toggle active account
            if user_active:
                if a2.button("🚫 Deactivate Account", key=f"deact_{did}", use_container_width=True):
                    try:
                        uid = doc.get("user_id", "")
                        if uid:
                            api.admin_toggle_user(uid)
                            st.session_state["admin_msg"] = f"Deactivated {doc['full_name']}"
                            st.rerun()
                    except Exception as e:
                        st.error(f"{e}")
            else:
                if a2.button("✅ Reactivate Account", key=f"react_{did}", use_container_width=True):
                    try:
                        uid = doc.get("user_id", "")
                        if uid:
                            api.admin_toggle_user(uid)
                            st.session_state["admin_msg"] = f"Reactivated {doc['full_name']}"
                            st.rerun()
                    except Exception as e:
                        st.error(f"{e}")

            # Edit — full profile + doctor settings
            with a3.popover("✏️ Edit", use_container_width=True):
                st.markdown("**Personal Details**")
                ed_name = st.text_input("Full Name", value=doc.get("full_name") or "", key=f"ed_name_{did}")
                ed_email = st.text_input("Email", value=doc.get("email") or "", key=f"ed_email_{did}")
                ed_phone = st.text_input("Phone", value=doc.get("phone") or "", key=f"ed_phone_{did}")
                st.divider()
                st.markdown("**Doctor Settings**")
                ed_spec = st.text_input("Specialization", doc.get("specialization") or "", key=f"ed_spec_{did}")
                ed_qual = st.text_input("Qualification", doc.get("qualification") or "", key=f"ed_qual_{did}")
                ed_license = st.text_input("License Number", doc.get("license_number") or "", key=f"ed_lic_{did}")
                ed_fee = st.number_input("Fee (₹)", 0, 10000, fee_val, key=f"ed_fee_{did}")
                ed_max = st.number_input("Max/Slot", 1, 10, max_val, key=f"ed_max_{did}")
                if st.button("💾 Save All", key=f"ed_save_{did}", type="primary", use_container_width=True):
                    # Personal details → admin_update_user
                    user_updates = {}
                    if ed_name and ed_name != (doc.get("full_name") or ""):
                        user_updates["full_name"] = ed_name
                    if ed_email and ed_email != (doc.get("email") or ""):
                        user_updates["email"] = ed_email
                    if ed_phone and ed_phone != (doc.get("phone") or ""):
                        user_updates["phone"] = ed_phone

                    # Doctor settings → admin_update_doctor
                    doc_updates = {}
                    if ed_fee != fee_val:
                        doc_updates["consultation_fee"] = ed_fee
                    if ed_max != max_val:
                        doc_updates["max_patients_per_slot"] = ed_max
                    if ed_spec != (doc.get("specialization") or ""):
                        doc_updates["specialization"] = ed_spec
                    if ed_qual != (doc.get("qualification") or ""):
                        doc_updates["qualification"] = ed_qual
                    if ed_license != (doc.get("license_number") or ""):
                        doc_updates["license_number"] = ed_license

                    if not user_updates and not doc_updates:
                        st.info("No changes")
                    else:
                        try:
                            if user_updates:
                                uid = doc.get("user_id", "")
                                if uid:
                                    api.admin_update_user(uid, user_updates)
                            if doc_updates:
                                api.admin_update_doctor(did, doc_updates)
                            st.session_state["admin_msg"] = f"Updated {ed_name or doc['full_name']}"
                            st.rerun()
                        except Exception as e:
                            st.error(f"{e}")


def _show_nurses_admins_tab():
    """List nurses and admins with toggle controls."""
    fc1, fc2 = st.columns([2, 1])
    role_filter = fc1.selectbox("Role", ["all", "nurse", "admin"], key="staff_na_role")
    show_inactive = fc2.checkbox("Show inactive", key="staff_na_inactive")

    try:
        users = api.admin_list_users(
            role="" if role_filter == "all" else role_filter,
            include_inactive=show_inactive,
        )
        # Exclude patients and doctors (doctors shown in their own tab)
        users = [u for u in users if u["role"] in ("nurse", "admin")]
    except Exception as e:
        st.error(f"Failed: {e}")
        return

    if not users:
        st.info("No staff found.")
        return

    for u in users:
        uid = str(u["id"])
        active = str(u.get("is_active", "True")).lower() == "true"
        role_icon = {"nurse": "💉", "admin": "🔧"}.get(u["role"], "•")
        status_dot = "🟢" if active else "🔴"

        with st.container(border=True):
            uc1, uc2, uc3 = st.columns([4, 1, 1])
            uc1.markdown(
                f"{status_dot} {role_icon} **{u['full_name']}** ({u['role']})  "
                f"•  {u.get('email', '—')}  •  📞 {u.get('phone') or '—'}"
            )
            uc2.caption(f"Since {str(u.get('created_at', ''))[:10]}")

            # Don't let admin deactivate themselves
            if u["role"] != "admin" or uid != str(st.session_state.user.get("user_id")):
                btn_label = "Deactivate" if active else "Activate"
                if uc3.button(btn_label, key=f"toggle_{uid}", use_container_width=True):
                    try:
                        r = api.admin_toggle_user(uid)
                        st.session_state["admin_msg"] = r["message"]
                        st.rerun()
                    except Exception as e:
                        st.error(f"{e}")


def _show_create_staff_form():
    """Create doctor/nurse/admin form."""
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


# ════════════════════════════════════════════════════════════
# 3. PATIENTS  (search, sort, view, edit, family, risk, appointments)
# ════════════════════════════════════════════════════════════

def page_admin_patients():
    """Patient management — search, sort, view, edit, family, risk, appointments."""
    from datetime import date as _d

    tc1, tc2 = st.columns([6, 1])
    tc1.title("🏥 Patient Management")
    if tc2.button("🔄 Refresh", key="refresh_admin_pat", use_container_width=True):
        st.rerun()

    if st.session_state.get("admin_msg"):
        st.success(st.session_state.pop("admin_msg"))

    # ── Filters row ──
    fc1, fc2, fc3 = st.columns([3, 1.5, 1.5])
    search = fc1.text_input("🔍 Search", key="admin_pat_search", placeholder="Name, phone, or ABHA...")
    sort_by = fc2.selectbox("Sort by", ["Newest first", "Oldest first", "Risk score", "Name A-Z"],
                             key="admin_pat_sort")
    sort_map = {"Newest first": "newest", "Oldest first": "oldest", "Risk score": "risk", "Name A-Z": "name"}

    # Department filter
    try:
        all_docs = api.admin_list_doctors()
    except Exception:
        all_docs = []
    departments = sorted(set(d.get("specialization", "") for d in all_docs if d.get("specialization")))
    filter_dept = fc3.selectbox("Department", ["All"] + departments, key="admin_pat_dept")

    # Second filter row: date range + toggles
    fd1, fd2, fd3, fd4, fd5 = st.columns([0.5, 1.5, 1.5, 1, 1])
    use_date_filter = fd1.checkbox("📅", key="admin_pat_use_date", help="Filter by registration date")
    if use_date_filter:
        filter_from = fd2.date_input("From", key="admin_pat_from")
        filter_to = fd3.date_input("To", key="admin_pat_to")
    else:
        filter_from = None
        filter_to = None
    high_risk = fd4.checkbox("High risk", key="admin_pat_hr")
    show_inactive = fd5.checkbox("Deactivated", key="admin_pat_inactive")

    try:
        patients = api.admin_list_patients(
            search=search if search and len(search) >= 2 else "",
            high_risk_only=high_risk,
            include_inactive=show_inactive,
            specialization="" if filter_dept == "All" else filter_dept,
            sort_by=sort_map.get(sort_by, "newest"),
            from_date=str(filter_from) if filter_from else "",
            to_date=str(filter_to) if filter_to else "",
        )
    except Exception as e:
        st.error(f"Failed: {e}")
        return

    if not patients:
        st.info("No patients found.")
        return

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

    # ── Patient cards ──
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
        reg_date = str(p.get("created_at", ""))[:10]

        # Beneficiary tag: show who added them
        added_by = p.get("added_by")
        added_as = p.get("added_as")
        is_beneficiary = str(p.get("is_beneficiary", "")).lower() == "true"
        fam_tag = ""
        if is_beneficiary and added_by and added_by != "None":
            rel_str = (added_as or "family").title() if added_as and added_as != "None" else "Family"
            fam_tag = f"  •  👤 {rel_str} of {added_by}"

        header = (
            f"{risk_dot} **{name}**{inactive_tag}  •  {age_str}/{gender_str}  "
            f"•  📞 {p.get('phone') or '—'}  •  Visits: {total_appt}  •  Reg: {reg_date}{fam_tag}"
        )

        with st.expander(header, expanded=False):
            _show_patient_detail(pid, name, risk, risk_dot)


def _show_patient_detail(pid: str, name: str, risk: float, risk_dot: str):
    """Expanded patient card — profile, family (add/edit), appointments, actions."""
    from datetime import date as _d

    try:
        detail = api.admin_get_patient(pid)
    except Exception as e:
        st.error(f"Could not load details: {e}")
        return

    age_str = ""
    if detail.get("date_of_birth") and detail["date_of_birth"] != "None":
        try:
            dob = _d.fromisoformat(str(detail["date_of_birth"])[:10])
            age_str = f"{(_d.today() - dob).days // 365}y"
        except Exception:
            pass

    # ── Profile info ──
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
            st.write(f"**Account Active:** {'✅ Yes' if detail.get('is_active') in ('True', 'true', True) else '❌ No'}")
            st.write(f"**Registered:** {str(detail.get('created_at', ''))[:10]}")

    # ── Family Members (view/edit inline + add) ──
    rels = detail.get("relationships", [])
    fam_label = f"👨‍👩‍👧‍👦 Family Members ({len(rels)})" if rels else "👨‍👩‍👧‍👦 Family Members"
    with st.expander(fam_label, expanded=False):
        if rels:
            for ri, r in enumerate(rels):
                b_pid = r.get("beneficiary_patient_id", "")
                b_name = r.get("beneficiary_name", "—")
                b_rel = (r.get("relationship_type") or "—").title()
                custom_rel = r.get("custom_relationship") or ""
                rel_display = f"{custom_rel.title()} (Other)" if b_rel == "Other" and custom_rel else b_rel
                b_approved = r.get("is_approved") in (True, "True", "true")

                with st.container(border=True):
                    # Header row
                    hdr1, hdr2 = st.columns([5, 2])
                    hdr1.markdown(f"**{b_name}** — {rel_display}  {'✅ Linked' if b_approved else '⏳ Pending'}")
                    edit_key = f"fam_edit_toggle_{pid}_{ri}"
                    if edit_key not in st.session_state:
                        st.session_state[edit_key] = False
                    if hdr2.button("✏️ Edit" if not st.session_state[edit_key] else "✕ Close",
                                   key=f"fam_toggle_{pid}_{ri}", use_container_width=True):
                        st.session_state[edit_key] = not st.session_state[edit_key]
                        st.rerun()

                    if b_pid:
                        try:
                            b_detail = api.admin_get_patient(b_pid)
                        except Exception as e:
                            st.error(f"Could not load: {e}")
                            continue

                        if not st.session_state[edit_key]:
                            # ── View mode: show details in a compact 2-col layout ──
                            vc1, vc2 = st.columns(2)
                            vc1.caption(f"📞 {b_detail.get('phone') or '—'}  •  📧 {b_detail.get('email') or '—'}")
                            _bg = (b_detail.get('gender') or '—').title()
                            _bb = b_detail.get('blood_group') or '—'
                            _bdob = b_detail.get('date_of_birth') or '—'
                            vc2.caption(f"⚧ {_bg}  •  🩸 {_bb}  •  🎂 {_bdob}")
                            _babha = b_detail.get('abha_id') or ''
                            _brisk = float(b_detail.get('risk_score') or 0)
                            _brd = "🟢" if _brisk < 3 else "🟡" if _brisk < 7 else "🔴"
                            if _babha:
                                st.caption(f"ABHA: {_babha}  •  Risk: {_brd} {_brisk:.1f}")
                            else:
                                st.caption(f"Risk: {_brd} {_brisk:.1f}")
                        else:
                            # ── Edit mode: full form pre-filled with existing data ──
                            ec1, ec2 = st.columns(2)
                            be_name = ec1.text_input("Name", value=b_detail.get("full_name") or "", key=f"be_fn_{pid}_{ri}")
                            be_phone = ec2.text_input("Phone", value=b_detail.get("phone") or "", key=f"be_ph_{pid}_{ri}")
                            ec3, ec4 = st.columns(2)
                            be_email = ec3.text_input("Email", value=b_detail.get("email") or "", key=f"be_em_{pid}_{ri}")
                            _be_dob_raw = str(b_detail.get("date_of_birth") or "")[:10]
                            be_dob_str = ec4.text_input("DOB (YYYY-MM-DD)", value=_be_dob_raw, key=f"be_dob_{pid}_{ri}")
                            ec5, ec6, ec7 = st.columns(3)
                            _be_g_opts = ["", "Male", "Female", "Other"]
                            _be_cur_g = b_detail.get("gender") or ""
                            _be_gi = _be_g_opts.index(_be_cur_g) if _be_cur_g in _be_g_opts else 0
                            be_gender = ec5.selectbox("Gender", _be_g_opts, index=_be_gi, key=f"be_gn_{pid}_{ri}")
                            _bg_opts = ["", "A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"]
                            be_blood = ec6.selectbox("Blood Group", _bg_opts,
                                                      index=_bg_opts.index(b_detail.get("blood_group") or ""),
                                                      key=f"be_bg_{pid}_{ri}")
                            be_abha = ec7.text_input("ABHA/UHID", value=b_detail.get("abha_id") or "", key=f"be_abha_{pid}_{ri}")
                            be_addr = st.text_input("Address", value=b_detail.get("address") or "", key=f"be_addr_{pid}_{ri}")
                            st.markdown("**Emergency Contact**")
                            ee1, ee2 = st.columns(2)
                            be_ec_name = ee1.text_input("Emergency Name", value=b_detail.get("emergency_contact_name") or "", key=f"be_ecn_{pid}_{ri}")
                            be_ec_phone = ee2.text_input("Emergency Phone", value=b_detail.get("emergency_contact_phone") or "", key=f"be_ecp_{pid}_{ri}")

                            if st.button("💾 Save Changes", key=f"be_save_{pid}_{ri}", type="primary", use_container_width=True):
                                b_payload = {}
                                _fields = [
                                    ("full_name", be_name), ("phone", be_phone), ("email", be_email),
                                    ("gender", be_gender), ("blood_group", be_blood), ("abha_id", be_abha),
                                    ("address", be_addr), ("emergency_contact_name", be_ec_name),
                                    ("emergency_contact_phone", be_ec_phone),
                                ]
                                for fkey, fval in _fields:
                                    if fval and fval != (b_detail.get(fkey) or ""):
                                        b_payload[fkey] = fval
                                if be_dob_str and be_dob_str != _be_dob_raw:
                                    b_payload["date_of_birth"] = be_dob_str
                                if b_payload:
                                    try:
                                        api.admin_update_patient(b_pid, b_payload)
                                        st.session_state[edit_key] = False
                                        st.session_state["admin_msg"] = f"Updated {be_name or b_name}"
                                        st.rerun()
                                    except Exception as ex:
                                        st.error(f"{ex}")
                                else:
                                    st.info("No changes.")
        else:
            st.info("No family members linked yet.")

        # ── Add new beneficiary ──
        st.divider()
        st.markdown("**➕ Add Family Member**")
        af1, af2 = st.columns(2)
        af_name = af1.text_input("Full Name *", key=f"af_name_{pid}", placeholder="e.g. Priya Kumar")
        _rel_types = ["parent", "child", "spouse", "sibling", "guardian", "other"]
        af_rel = af2.selectbox("Relationship *", _rel_types, key=f"af_rel_{pid}")

        af_custom_rel = ""
        if af_rel == "other":
            af_custom_rel = st.text_input("Specify relationship type *", key=f"af_custom_{pid}",
                                           placeholder="e.g. cousin, uncle, caretaker")

        af3, af4, af5 = st.columns(3)
        af_phone = af3.text_input("Phone", key=f"af_phone_{pid}")
        af_gender = af4.selectbox("Gender", ["male", "female", "other"], key=f"af_gender_{pid}")
        af_blood = af5.selectbox("Blood Group", ["", "A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"],
                                  key=f"af_blood_{pid}")

        if st.button("➕ Add Member", key=f"af_add_{pid}", type="primary"):
            if not af_name or len(af_name.strip()) < 2:
                st.error("Name is required (min 2 characters).")
            elif af_rel == "other" and not af_custom_rel.strip():
                st.error("Please specify the relationship type.")
            else:
                payload = {
                    "beneficiary_name": af_name.strip(),
                    "relationship_type": af_rel,
                    "phone": af_phone.strip() if af_phone else "",
                    "gender": af_gender,
                    "blood_group": af_blood if af_blood else None,
                }
                if af_rel == "other" and af_custom_rel.strip():
                    payload["custom_relationship"] = af_custom_rel.strip()
                try:
                    r = api.admin_add_beneficiary(pid, payload)
                    st.session_state["admin_msg"] = r.get("message", f"Added {af_name}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed: {e}")

    # ── Appointments ──
    appts = detail.get("appointments", [])
    if appts:
        with st.expander(f"📋 Appointments ({len(appts)})", expanded=False):
            for a in appts:
                a_status = a.get("status", "—")
                a_id = a.get("appointment_id", "")
                a_icon = {"booked": "📅", "checked_in": "✅", "in_progress": "🔄",
                          "completed": "✔️", "no_show": "⚠️", "cancelled": "❌"}.get(a_status, "•")
                slot_t = a.get("slot_time") or str(a.get("start_time", ""))[:5]
                a_date = a.get("session_date", "—")
                doc_name = a.get("doctor_name", "—")
                spec = a.get("specialization", "")

                with st.container(border=True):
                    ac1, ac2, ac3, ac4 = st.columns([3, 2.5, 1, 1.5])
                    ac1.write(f"{a_icon} **{a_status.replace('_', ' ').title()}** — {a_date} {slot_t}")
                    ac2.write(f"🩺 {doc_name} ({spec})")
                    if a_status == "booked":
                        if ac3.button("✖ Cancel", key=f"adm_cx_{a_id}", use_container_width=True):
                            try:
                                api.staff_cancel_appointment({"appointment_id": a_id, "reason": f"Cancelled by {st.session_state.get('user', {}).get('role', 'staff')}"})
                                st.session_state["admin_msg"] = f"Cancelled appointment for {name}"
                                st.rerun()
                            except Exception as ex:
                                st.error(f"{ex}")
                        # Reassign popover
                        with ac4.popover("🔄 Reassign", use_container_width=True):
                            _reassign_form(a_id, name, pid)
                    elif a_status == "checked_in":
                        # Can also reassign checked-in appointments
                        with ac3.popover("🔄 Reassign", use_container_width=True):
                            _reassign_form(a_id, name, pid)
                    elif a_status == "no_show":
                        if ac3.button("↩ Undo", key=f"adm_uns_{a_id}", use_container_width=True):
                            try:
                                api.undo_noshow({"appointment_id": a_id})
                                st.session_state["admin_msg"] = f"No-show undone for {name}"
                                st.rerun()
                            except Exception as ex:
                                st.error(f"{ex}")
                    elif a_status == "cancelled":
                        if ac3.button("↩ Restore", key=f"adm_ucx_{a_id}", use_container_width=True):
                            try:
                                api.undo_cancel({"appointment_id": a_id})
                                st.session_state["admin_msg"] = f"Appointment restored for {name}"
                                st.rerun()
                            except Exception as ex:
                                st.error(f"{ex}")
                    if a.get("notes") and a["notes"] != "None":
                        st.caption(f"📝 {a['notes']}")

    # ── Admin Actions ──
    st.divider()
    act1, act2, act3, act4, act5 = st.columns(5)

    # Edit profile
    with act1.popover("✏️ Edit Profile", use_container_width=True):
        _patient_edit_form(pid, name, detail)

    # Risk reset
    with act2.popover("🔧 Reset Risk", use_container_width=True):
        new_risk = st.number_input("New score", 0.0, 10.0, 0.0, step=0.5, key=f"rr_{pid}")
        if st.button("Reset", key=f"rr_btn_{pid}", type="primary", use_container_width=True):
            try:
                api.admin_reset_risk(pid, new_risk)
                st.session_state["admin_msg"] = f"Risk reset to {new_risk} for {name}"
                st.rerun()
            except Exception as e:
                st.error(f"{e}")

    # Book appointment (regular — needs slot)
    with act3.popover("📅 Book Appt", use_container_width=True):
        _patient_book_form(pid, name, detail)

    # Emergency booking — no slot required
    with act4.popover("🚨 Emergency", use_container_width=True):
        _emergency_book_form(pid, name, detail)

    # Toggle active — admin only
    if st.session_state.get("user", {}).get("role") == "admin":
        is_active = detail.get("is_active") in ("True", "true", True)
        toggle_label = "🚫 Deactivate" if is_active else "✅ Reactivate"
        if act5.button(toggle_label, key=f"toggle_{pid}", use_container_width=True):
            try:
                uid = detail.get("user_id", "")
                if uid and uid != "None":
                    api.admin_toggle_user(uid)
                    status_word = "deactivated" if is_active else "reactivated"
                    st.session_state["admin_msg"] = f"Account {status_word} for {name}"
                    st.rerun()
            except Exception as e:
                st.error(f"{e}")


def _patient_edit_form(pid: str, name: str, detail: dict):
    """Edit patient profile popover form — all fields pre-filled with existing data."""
    st.markdown("**Edit Patient Profile**")
    ep1, ep2 = st.columns(2)
    ep_name = ep1.text_input("Full Name", value=detail.get("full_name") or name or "", key=f"ep_fn_{pid}")
    ep_email = ep2.text_input("Email", value=detail.get("email") or "", key=f"ep_em_{pid}")
    ep3, ep4 = st.columns(2)
    ep_phone = ep3.text_input("Phone", value=detail.get("phone") or "", key=f"ep_ph_{pid}")
    _dob_raw = str(detail.get("date_of_birth") or "")[:10]
    ep_dob = ep4.text_input("DOB (YYYY-MM-DD)", value=_dob_raw, key=f"ep_dob_{pid}")
    ep5, ep6, ep7 = st.columns(3)
    _gender_opts = ["", "Male", "Female", "Other"]
    _cur_gender = detail.get("gender") or ""
    _gi = _gender_opts.index(_cur_gender) if _cur_gender in _gender_opts else 0
    ep_gender = ep5.selectbox("Gender", _gender_opts, index=_gi, key=f"ep_gn_{pid}")
    _bg_opts = ["", "A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"]
    ep_blood = ep6.selectbox("Blood Group", _bg_opts,
                              index=_bg_opts.index(detail.get("blood_group") or ""), key=f"ep_bg_{pid}")
    ep_abha = ep7.text_input("ABHA/UHID", value=detail.get("abha_id") or "", key=f"ep_abha_{pid}")
    ep_addr = st.text_input("Address", value=detail.get("address") or "", key=f"ep_addr_{pid}")
    st.divider()
    st.markdown("**Emergency Contact**")
    epc1, epc2 = st.columns(2)
    ep_ec_name = epc1.text_input("Emergency Name", value=detail.get("emergency_contact_name") or "", key=f"ep_ecn_{pid}")
    ep_ec_phone = epc2.text_input("Emergency Phone", value=detail.get("emergency_contact_phone") or "", key=f"ep_ecp_{pid}")

    if st.button("💾 Save", key=f"ep_save_{pid}", type="primary", use_container_width=True):
        payload = {}
        _fields = [
            ("full_name", ep_name, detail.get("full_name") or name or ""),
            ("email", ep_email, detail.get("email") or ""),
            ("phone", ep_phone, detail.get("phone") or ""),
            ("gender", ep_gender, detail.get("gender") or ""),
            ("blood_group", ep_blood, detail.get("blood_group") or ""),
            ("abha_id", ep_abha, detail.get("abha_id") or ""),
            ("address", ep_addr, detail.get("address") or ""),
            ("emergency_contact_name", ep_ec_name, detail.get("emergency_contact_name") or ""),
            ("emergency_contact_phone", ep_ec_phone, detail.get("emergency_contact_phone") or ""),
        ]
        for fkey, fval, foriginal in _fields:
            if fval and fval != foriginal:
                payload[fkey] = fval
        if ep_dob and ep_dob != _dob_raw:
            payload["date_of_birth"] = ep_dob
        if payload:
            try:
                api.admin_update_patient(pid, payload)
                st.session_state["admin_msg"] = f"Profile updated for {ep_name or name}"
                st.rerun()
            except Exception as e:
                st.error(f"{e}")
        else:
            st.info("No changes to save.")


def _patient_book_form(pid: str, name: str, detail: dict):
    """Book appointment for a patient — compact popover form."""
    from datetime import date as _bk_d, datetime as _bk_dt

    st.markdown(f"**Book for {name}**")

    # Who to book for (self or family member)
    bk_for_options = [f"{name} (Self)"]
    bk_for_ids = {0: pid}
    bk_rels = detail.get("relationships", [])
    for ri, rel in enumerate(bk_rels):
        bname = rel.get("beneficiary_name", "?")
        rtype = (rel.get("relationship_type") or "other").title()
        bk_for_options.append(f"{bname} ({rtype})")
        bk_for_ids[ri + 1] = rel.get("beneficiary_patient_id", pid)

    if len(bk_for_options) > 1:
        bk_for_idx = st.radio("Booking for", bk_for_options, key=f"bk_for_{pid}", horizontal=False)
        bk_for_sel = bk_for_options.index(bk_for_idx) if bk_for_idx in bk_for_options else 0
    else:
        bk_for_sel = 0
    bk_patient_id = bk_for_ids.get(bk_for_sel, pid)
    bk_patient_name = bk_for_options[bk_for_sel].split(" (")[0]

    # Doctor selection
    try:
        bk_docs = api.list_doctors()
    except Exception:
        bk_docs = []

    if not bk_docs:
        st.warning("No doctors available.")
        return

    bk_doc_labels = [f"{d['full_name']} ({d['specialization']})" for d in bk_docs]
    bk_doc_idx = st.selectbox("Doctor", range(len(bk_doc_labels)),
                               format_func=lambda i: bk_doc_labels[i], key=f"bk_doc_{pid}")
    bk_doc = bk_docs[bk_doc_idx]

    # Date
    _bk_today = _bk_d.today()
    bk_date = st.date_input("Date", value=_bk_today, min_value=_bk_today, key=f"bk_date_{pid}")

    try:
        bk_sessions = api.get_doctor_sessions(
            bk_doc["doctor_id"],
            from_date=str(bk_date),
            to_date=str(bk_date),
            include_all=True,
        )
        bk_bookable = [s for s in bk_sessions if s.get("status") in ("active", "inactive")]
        # Filter out sessions that have already ended today
        if str(bk_date) == str(_bk_d.today()):
            _now_min = _bk_dt.now().hour * 60 + _bk_dt.now().minute
            _still_open = []
            for s in bk_bookable:
                try:
                    et = str(s.get("end_time", ""))[:5]
                    end_min = int(et[:2]) * 60 + int(et[3:5])
                    if end_min > _now_min:
                        _still_open.append(s)
                except (ValueError, IndexError):
                    _still_open.append(s)
            bk_bookable = _still_open
    except Exception:
        bk_bookable = []

    if not bk_bookable:
        st.info("No sessions available for this date.")
        return

    def _sess_label(s):
        tag = " ⚪ INACTIVE" if s.get("status") == "inactive" else ""
        cap = s.get('available_capacity', '?')
        return (f"{str(s.get('start_time', ''))[:5]}–{str(s.get('end_time', ''))[:5]} "
                f"• {cap} slots{tag}")

    bk_sess_idx = st.selectbox("Session", range(len(bk_bookable)),
                                format_func=lambda i: _sess_label(bk_bookable[i]),
                                key=f"bk_sess_{pid}")
    bk_sess = bk_bookable[bk_sess_idx]

    if bk_sess.get("status") == "inactive":
        st.warning("Session is inactive. Activate first.")
        if st.button("🟢 Activate", key=f"bk_activate_{pid}"):
            try:
                api.activate_session({"session_id": bk_sess["session_id"]})
                st.rerun()
            except Exception as e:
                st.error(f"{e}")
        return

    # Slot picker
    bk_total = bk_sess.get("total_slots", 1)
    bk_dur = bk_sess.get("slot_duration_minutes", 15)
    bk_start = str(bk_sess.get("start_time", "09:00"))
    _bk_now_min = _bk_dt.now().hour * 60 + _bk_dt.now().minute
    _bk_is_today = str(bk_date) == str(_bk_d.today())
    bk_slot_opts = []
    for si in range(1, bk_total + 1):
        try:
            hh, mm = int(bk_start[:2]), int(bk_start[3:5])
            t_min = hh * 60 + mm + (si - 1) * bk_dur
            if _bk_is_today and t_min <= _bk_now_min:
                continue
            t_str = f"{t_min // 60:02d}:{t_min % 60:02d}"
        except Exception:
            t_str = f"Slot {si}"
        bk_slot_opts.append((si, f"Slot {si} — {t_str}"))

    if not bk_slot_opts:
        st.warning("All slots have passed.")
        return

    bk_slot_idx = st.selectbox("Time", range(len(bk_slot_opts)),
                                format_func=lambda i: bk_slot_opts[i][1], key=f"bk_slot_{pid}")
    bk_slot_num = bk_slot_opts[bk_slot_idx][0]

    if st.button("✅ Book", key=f"bk_confirm_{pid}", type="primary", use_container_width=True):
        try:
            api.staff_book({
                "session_id": bk_sess["session_id"],
                "patient_id": bk_patient_id,
                "slot_number": bk_slot_num,
            })
            st.session_state["admin_msg"] = f"Booked {bk_patient_name} with {bk_doc['full_name']}"
            st.rerun()
        except Exception as ex:
            st.error(f"Booking failed: {ex}")


def _reassign_form(appointment_id: str, patient_name: str, patient_id: str):
    """Reassign an appointment to a different doctor/session/slot — with reason."""
    from datetime import date as _ra_d, datetime as _ra_dt

    st.markdown(f"**Reassign for {patient_name}**")
    st.caption("Move this appointment to a different doctor, session, or time slot.")

    # Reason
    ra_reason = st.text_input("Reason *", key=f"ra_reason_{appointment_id}",
                               placeholder="e.g. Doctor unavailable, patient preference")

    # Doctor selection
    try:
        ra_docs = api.list_doctors()
    except Exception:
        ra_docs = []

    if not ra_docs:
        st.warning("No doctors available.")
        return

    ra_doc_labels = [f"{d['full_name']} ({d['specialization']})" for d in ra_docs]
    ra_doc_idx = st.selectbox("Doctor", range(len(ra_doc_labels)),
                               format_func=lambda i: ra_doc_labels[i], key=f"ra_doc_{appointment_id}")
    ra_doc = ra_docs[ra_doc_idx]

    # Date
    ra_date = st.date_input("Date", value=_ra_d.today(), min_value=_ra_d.today(), key=f"ra_date_{appointment_id}")

    try:
        ra_sessions = api.get_doctor_sessions(
            ra_doc["doctor_id"], from_date=str(ra_date), to_date=str(ra_date), include_all=True,
        )
        ra_active = [s for s in ra_sessions if s.get("status") == "active"]
        # Filter out sessions that ended today
        if str(ra_date) == str(_ra_d.today()):
            _ra_now = _ra_dt.now().hour * 60 + _ra_dt.now().minute
            _ra_open = []
            for s in ra_active:
                try:
                    et = str(s.get("end_time", ""))[:5]
                    end_min = int(et[:2]) * 60 + int(et[3:5])
                    if end_min > _ra_now:
                        _ra_open.append(s)
                except (ValueError, IndexError):
                    _ra_open.append(s)
            ra_active = _ra_open
    except Exception:
        ra_active = []

    if not ra_active:
        st.info("No active sessions for this doctor on this date.")
        return

    def _ra_sess_lbl(s):
        cap = s.get("available_capacity", "?")
        return f"{str(s.get('start_time', ''))[:5]}–{str(s.get('end_time', ''))[:5]} • {cap} slots"

    ra_sess_idx = st.selectbox("Session", range(len(ra_active)),
                                format_func=lambda i: _ra_sess_lbl(ra_active[i]),
                                key=f"ra_sess_{appointment_id}")
    ra_sess = ra_active[ra_sess_idx]

    # Slot picker
    ra_total = ra_sess.get("total_slots", 1)
    ra_dur = ra_sess.get("slot_duration_minutes", 15)
    ra_start = str(ra_sess.get("start_time", "09:00"))
    ra_slot_opts = []
    _ra_now_min = _ra_dt.now().hour * 60 + _ra_dt.now().minute
    _ra_is_today = str(ra_date) == str(_ra_d.today())
    for si in range(1, ra_total + 1):
        try:
            hh, mm = int(ra_start[:2]), int(ra_start[3:5])
            t_min = hh * 60 + mm + (si - 1) * ra_dur
            if _ra_is_today and t_min <= _ra_now_min:
                continue
            t_str = f"{t_min // 60:02d}:{t_min % 60:02d}"
        except Exception:
            t_str = f"Slot {si}"
        ra_slot_opts.append((si, f"Slot {si} — {t_str}"))

    if not ra_slot_opts:
        st.warning("All slots have passed.")
        return

    ra_slot_idx = st.selectbox("Time", range(len(ra_slot_opts)),
                                format_func=lambda i: ra_slot_opts[i][1], key=f"ra_slot_{appointment_id}")
    ra_slot_num = ra_slot_opts[ra_slot_idx][0]

    if st.button("🔄 Reassign", key=f"ra_confirm_{appointment_id}", type="primary", use_container_width=True):
        if not ra_reason or len(ra_reason.strip()) < 3:
            st.error("Please provide a reason.")
        else:
            try:
                api.reassign_appointment({
                    "appointment_id": appointment_id,
                    "target_session_id": ra_sess["session_id"],
                    "target_slot_number": ra_slot_num,
                })
                st.session_state["admin_msg"] = (
                    f"Reassigned {patient_name} to {ra_doc['full_name']} "
                    f"(Slot {ra_slot_num}) — Reason: {ra_reason.strip()}"
                )
                st.rerun()
            except Exception as ex:
                st.error(f"Reassign failed: {ex}")


def _emergency_book_form(pid: str, name: str, detail: dict):
    """Emergency booking — no slot needed, just doctor + priority + reason."""
    from datetime import date as _em_d

    st.markdown(f"**🚨 Emergency for {name}**")
    st.caption("No time slot required — patient goes directly into the emergency queue.")

    # Who to book for (self or family member)
    em_for_options = [f"{name} (Self)"]
    em_for_ids = {0: pid}
    em_rels = detail.get("relationships", [])
    for ri, rel in enumerate(em_rels):
        bname = rel.get("beneficiary_name", "?")
        rtype = (rel.get("relationship_type") or "other").title()
        em_for_options.append(f"{bname} ({rtype})")
        em_for_ids[ri + 1] = rel.get("beneficiary_patient_id", pid)

    if len(em_for_options) > 1:
        em_for_idx = st.radio("Patient", em_for_options, key=f"em_for_{pid}", horizontal=False)
        em_for_sel = em_for_options.index(em_for_idx) if em_for_idx in em_for_options else 0
    else:
        em_for_sel = 0
    em_patient_id = em_for_ids.get(em_for_sel, pid)
    em_patient_name = em_for_options[em_for_sel].split(" (")[0]

    # Doctor / specialization selection
    try:
        em_docs = api.list_doctors()
    except Exception:
        em_docs = []

    if not em_docs:
        st.warning("No doctors available.")
        return

    # Group by specialization for quick filtering
    specs = sorted(set(d.get("specialization", "") for d in em_docs if d.get("specialization")))
    em_spec = st.selectbox("Specialization", ["All"] + specs, key=f"em_spec_{pid}")
    if em_spec != "All":
        em_docs = [d for d in em_docs if d.get("specialization") == em_spec]

    em_doc_labels = [f"{d['full_name']} ({d['specialization']})" for d in em_docs]
    em_doc_idx = st.selectbox("Doctor", range(len(em_doc_labels)),
                               format_func=lambda i: em_doc_labels[i], key=f"em_doc_{pid}")
    em_doc = em_docs[em_doc_idx]

    # Find an active session for this doctor today
    _em_today = _em_d.today()
    try:
        em_sessions = api.get_doctor_sessions(
            em_doc["doctor_id"], from_date=str(_em_today), to_date=str(_em_today), include_all=True,
        )
        em_active = [s for s in em_sessions if s.get("status") == "active"]
    except Exception:
        em_active = []

    if not em_active:
        st.warning(f"No active session today for {em_doc['full_name']}. Activate one first.")
        return

    if len(em_active) > 1:
        def _em_sess_lbl(s):
            return f"{str(s.get('start_time', ''))[:5]}–{str(s.get('end_time', ''))[:5]}"
        em_sess_idx = st.selectbox("Session", range(len(em_active)),
                                    format_func=lambda i: _em_sess_lbl(em_active[i]), key=f"em_sess_{pid}")
    else:
        em_sess_idx = 0
    em_sess = em_active[em_sess_idx]

    # Priority
    em_priority = st.selectbox("Priority", ["CRITICAL", "HIGH", "NORMAL"], key=f"em_pri_{pid}")

    # Reason
    em_reason = st.text_area("Reason *", key=f"em_reason_{pid}", placeholder="Describe the emergency...",
                              height=80)

    if st.button("🚨 Add to Emergency Queue", key=f"em_confirm_{pid}", type="primary", use_container_width=True):
        if not em_reason or len(em_reason.strip()) < 5:
            st.error("Please provide a reason (min 5 characters).")
        else:
            try:
                api.emergency_book({
                    "session_id": em_sess["session_id"],
                    "patient_id": em_patient_id,
                    "reason": em_reason.strip(),
                    "priority_tier": em_priority,
                })
                st.session_state["admin_msg"] = (
                    f"🚨 {em_patient_name} added to emergency queue with {em_doc['full_name']} "
                    f"— Priority: {em_priority}"
                )
                st.rerun()
            except Exception as ex:
                st.error(f"Emergency booking failed: {ex}")


# ════════════════════════════════════════════════════════════
# 4. SESSIONS  (overview + cancel — merged)
# ════════════════════════════════════════════════════════════

def page_admin_sessions():
    """Session management — date-first view showing ALL doctors and their session status."""
    from datetime import date as _date_cls, time as _time_cls

    tc1, tc2 = st.columns([6, 1])
    tc1.title("📅 Sessions")
    if tc2.button("🔄 Refresh", key="refresh_admin_sess", use_container_width=True):
        st.rerun()

    if st.session_state.get("admin_msg"):
        st.success(st.session_state.pop("admin_msg"))

    try:
        all_docs = api.admin_list_doctors()
    except Exception:
        all_docs = []

    departments = sorted(set(d.get("specialization", "") for d in all_docs if d.get("specialization")))

    # ── Date + Department filter ──
    fc1, fc2 = st.columns([1, 1])
    filter_date = fc1.date_input("📅 Select Date", value=_date_cls.today(), key="admin_sess_date")
    filter_dept = fc2.selectbox("Department", ["All"] + departments, key="admin_sess_dept")

    if filter_dept != "All":
        filtered_docs = [d for d in all_docs if d.get("specialization") == filter_dept]
    else:
        filtered_docs = all_docs

    if not filtered_docs:
        st.info("No doctors registered.")
        return

    # Fetch ALL sessions for selected date (no doctor filter — we want to see everyone)
    try:
        all_sessions = api.admin_list_sessions(
            date_str=str(filter_date),
            specialization="" if filter_dept == "All" else filter_dept,
        )
    except Exception as e:
        st.error(f"Failed: {e}")
        all_sessions = []

    # Group sessions by doctor_id
    sessions_by_doc = {}
    for s in all_sessions:
        did = s.get("doctor_id", "")
        sessions_by_doc.setdefault(did, []).append(s)

    # Summary metrics
    docs_with_active = sum(1 for did in sessions_by_doc
                           if any(str(s.get("status", "")).lower() == "active" for s in sessions_by_doc[did]))
    docs_with_inactive = sum(1 for did in sessions_by_doc
                             if any(str(s.get("status", "")).lower() == "inactive" for s in sessions_by_doc[did])
                             and not any(str(s.get("status", "")).lower() == "active" for s in sessions_by_doc[did]))
    docs_no_session = len(filtered_docs) - len(set(sessions_by_doc.keys()) &
                          set(str(d["doctor_id"]) for d in filtered_docs))
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Total Doctors", len(filtered_docs))
    mc2.metric("🟢 Active Sessions", docs_with_active)
    mc3.metric("🟡 Inactive Only", docs_with_inactive)
    mc4.metric("⚪ No Session", docs_no_session)
    st.divider()

    # ── Doctor cards for this date ──
    for doc in filtered_docs:
        did = str(doc["doctor_id"])
        doc_name = doc["full_name"]
        spec = doc.get("specialization") or "—"
        doc_avail = str(doc.get("is_available", "True")).lower() == "true"
        doc_sessions = sessions_by_doc.get(did, [])

        # Determine doctor status for this date
        has_active = any(str(s.get("status", "")).lower() == "active" for s in doc_sessions)
        has_inactive = any(str(s.get("status", "")).lower() == "inactive" for s in doc_sessions)

        if has_active:
            status_icon = "🟢"
            status_text = "Active"
        elif has_inactive:
            status_icon = "🟡"
            status_text = "Inactive"
        elif doc_sessions:
            status_icon = "⚪"
            status_text = "Completed/Cancelled"
        else:
            status_icon = "🔴" if not doc_avail else "⚪"
            status_text = "Unavailable" if not doc_avail else "No Session"

        # Build session summary for header
        if doc_sessions:
            active_sess = [s for s in doc_sessions if str(s.get("status", "")).lower() in ("active", "inactive")]
            if active_sess:
                times = [f"{str(s.get('start_time', ''))[:5]}–{str(s.get('end_time', ''))[:5]}" for s in active_sess]
                total_booked = sum(int(s.get("booked_count") or 0) for s in active_sess)
                total_slots = sum(int(s.get("total_slots") or 0) for s in active_sess)
                sess_info = f" • {', '.join(times)} • {total_booked}/{total_slots} booked"
            else:
                sess_info = f" • {len(doc_sessions)} session(s)"
        else:
            sess_info = ""

        avail_tag = "" if doc_avail else " • ⚠️ Unavailable"

        with st.expander(
            f"{status_icon} **{doc_name}** ({spec}) — {status_text}{sess_info}{avail_tag}",
            expanded=False,
        ):
            # ── Unavailability warning + fix ──
            if not doc_avail:
                wa1, wa2 = st.columns([3, 1])
                wa1.warning(f"**{doc_name}** is marked as unavailable.")
                if wa2.button("✅ Set Available", key=f"avail_{did}_{filter_date}", use_container_width=True):
                    try:
                        api.admin_update_doctor(did, {"is_available": True})
                        st.session_state["admin_msg"] = f"{doc_name} set as available"
                        st.rerun()
                    except Exception as e:
                        st.error(f"{e}")

            # ── Existing sessions for this doctor on this date ──
            if doc_sessions:
                for s in doc_sessions:
                    s_status = str(s.get("status", "")).lower()
                    s_icon = {"active": "🟢", "inactive": "🟡", "completed": "✅", "cancelled": "❌"}.get(s_status, "•")
                    s_start = str(s.get("start_time", ""))[:5]
                    s_end = str(s.get("end_time", ""))[:5]
                    s_booked = s.get("booked_count", "0")
                    s_total = s.get("total_slots", "0")
                    s_delay = s.get("delay_minutes", "0")
                    session_id = s.get("session_id") or s.get("id")
                    s_detail = f"{s_booked}/{s_total} booked"
                    if str(s_delay) != "0":
                        s_detail += f" • ⏰ {s_delay}min delay"

                    with st.container(border=True):
                        st.write(f"{s_icon} **{s_start}–{s_end}** • {s_detail} • _{s_status.title()}_")
                        st.caption(f"Duration: {s.get('slot_duration_minutes', 15)}min/slot • Max: {s.get('max_patients_per_slot', 2)}/slot")

                        ac1, ac2, ac3, ac4 = st.columns(4)

                        # Activate / Deactivate
                        if s_status == "active":
                            if ac1.button("⏸ Deactivate", key=f"deact_{session_id}", use_container_width=True):
                                try:
                                    api.deactivate_session({"session_id": session_id})
                                    st.session_state["admin_msg"] = "Session deactivated"
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"{e}")
                        elif s_status == "inactive":
                            if ac1.button("▶️ Activate", key=f"act_{session_id}", use_container_width=True):
                                try:
                                    api.activate_session({"session_id": session_id})
                                    st.session_state["admin_msg"] = "Session activated"
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"{e}")

                        # Cancel
                        if s_status in ("active", "inactive"):
                            with ac2.popover("❌ Cancel"):
                                st.warning("Cancels ALL appointments. No penalties.")
                                cx_reason = st.text_input("Reason", key=f"cx_r_{session_id}",
                                                           placeholder="e.g. Doctor unavailable")
                                if st.button("Confirm", key=f"cx_btn_{session_id}", type="primary",
                                             use_container_width=True):
                                    if not cx_reason or len(cx_reason) < 5:
                                        st.error("Reason required (5+ chars).")
                                    else:
                                        try:
                                            r = api.cancel_session({"session_id": session_id, "reason": cx_reason})
                                            st.session_state["admin_msg"] = (
                                                f"Cancelled — {r.get('appointments_cancelled', 0)} appointments affected"
                                            )
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"{e}")

                        # Edit
                        if s_status in ("active", "inactive"):
                            with ac3.popover("✏️ Edit"):
                                _cur_start = s_start
                                _cur_end = s_end
                                try:
                                    _cst = _time_cls(int(_cur_start[:2]), int(_cur_start[3:5]))
                                except Exception:
                                    _cst = _time_cls(9, 0)
                                try:
                                    _cet = _time_cls(int(_cur_end[:2]), int(_cur_end[3:5]))
                                except Exception:
                                    _cet = _time_cls(13, 0)
                                e1, e2 = st.columns(2)
                                es_st = e1.time_input("Start", value=_cst, key=f"es_st_{session_id}")
                                es_et = e2.time_input("End", value=_cet, key=f"es_et_{session_id}")
                                e3, e4 = st.columns(2)
                                es_dur = e3.number_input("Slot min", value=int(s.get("slot_duration_minutes") or 15),
                                                          min_value=5, max_value=60, step=5, key=f"es_dur_{session_id}")
                                es_max = e4.number_input("Max/slot", value=int(s.get("max_patients_per_slot") or 2),
                                                          min_value=1, max_value=10, key=f"es_max_{session_id}")
                                if st.button("💾 Save", key=f"es_save_{session_id}", type="primary",
                                             use_container_width=True):
                                    payload = {}
                                    if es_st.strftime("%H:%M") != _cur_start:
                                        payload["start_time"] = es_st.strftime("%H:%M")
                                    if es_et.strftime("%H:%M") != _cur_end:
                                        payload["end_time"] = es_et.strftime("%H:%M")
                                    if es_dur != int(s.get("slot_duration_minutes") or 15):
                                        payload["slot_duration_minutes"] = es_dur
                                    if es_max != int(s.get("max_patients_per_slot") or 2):
                                        payload["max_patients_per_slot"] = es_max
                                    if payload:
                                        try:
                                            api.admin_update_session(str(session_id), payload)
                                            st.session_state["admin_msg"] = f"Session updated"
                                            st.rerun()
                                        except Exception as ex:
                                            st.error(f"{ex}")
                                    else:
                                        st.info("No changes.")

                        # Queue
                        with ac4.popover("👁️ Queue"):
                            try:
                                q = api.get_queue(session_id)
                                queue_items = q.get("queue", [])
                                st.caption(f"Total: {q.get('total_in_queue', 0)}")
                                if queue_items:
                                    for qi in queue_items:
                                        qi_s = qi.get("status", "—")
                                        qi_icon = {"checked_in": "✅", "in_progress": "🔄",
                                                   "completed": "✔️", "booked": "📅",
                                                   "no_show": "⚠️"}.get(qi_s, "•")
                                        emg = " 🚨" if qi.get("is_emergency") else ""
                                        st.write(f"{qi_icon} **{qi.get('patient_name', '—')}**{emg} — "
                                                 f"Slot {qi.get('slot_number', '—')}")
                                else:
                                    st.info("Empty.")
                            except Exception as e:
                                st.error(f"{e}")

                        if s.get("notes") and s["notes"] != "None":
                            st.caption(f"📝 {s['notes']}")
            else:
                st.info(f"No sessions on {filter_date.strftime('%b %d, %Y')}")

            # ── Quick create session for this doctor ──
            st.divider()
            with st.popover("➕ Create Session", use_container_width=True):
                st.markdown(f"**New session for {doc_name}**")
                nc1, nc2 = st.columns(2)
                nc_start = nc1.time_input("Start", value=_time_cls(9, 0), key=f"nc_st_{did}_{filter_date}")
                nc_end = nc2.time_input("End", value=_time_cls(13, 0), key=f"nc_et_{did}_{filter_date}")
                nc3, nc4 = st.columns(2)
                nc_dur = nc3.number_input("Slot (min)", value=15, min_value=5, max_value=60,
                                           step=5, key=f"nc_dur_{did}_{filter_date}")
                nc_max = nc4.number_input("Max/slot", value=2, min_value=1, max_value=10,
                                           key=f"nc_max_{did}_{filter_date}")
                if nc_start < nc_end:
                    nc_slots = ((nc_end.hour * 60 + nc_end.minute) - (nc_start.hour * 60 + nc_start.minute)) // nc_dur
                    st.caption(f"→ {nc_slots} slots")
                if st.button("➕ Create", key=f"nc_btn_{did}_{filter_date}", type="primary",
                             use_container_width=True):
                    if filter_date < _date_cls.today():
                        st.error("Cannot create a session for a past date.")
                    elif nc_start >= nc_end:
                        st.error("Start must be before end.")
                    else:
                        try:
                            r = api.create_session({
                                "doctor_id": did,
                                "session_date": str(filter_date),
                                "start_time": nc_start.strftime("%H:%M"),
                                "end_time": nc_end.strftime("%H:%M"),
                                "slot_duration_minutes": nc_dur,
                                "max_patients_per_slot": nc_max,
                            })
                            st.session_state["admin_msg"] = r.get("message", "Session created")
                            st.rerun()
                        except Exception as e:
                            st.error(f"{e}")


# ════════════════════════════════════════════════════════════
# 5. AUDIT LOGS
# ════════════════════════════════════════════════════════════

def page_admin_audit():
    """Audit log viewer — all system actions."""
    tc1, tc2 = st.columns([6, 1])
    tc1.title("📜 Audit Logs")
    if tc2.button("🔄 Refresh", key="refresh_admin_audit", use_container_width=True):
        st.rerun()

    from datetime import date as _date_cls
    fc1, fc2, fc3 = st.columns(3)
    action_filter = fc1.selectbox(
        "Action",
        ["all", "BOOKED", "CANCELLED", "SESSION_CANCELLED", "WAITLISTED",
         "check_in", "complete_session", "activate_session", "deactivate_session",
         "reschedule", "escalate_priority"],
        key="audit_action",
    )
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
    st.caption(f"Showing {len(logs)} of {total} entries")

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
