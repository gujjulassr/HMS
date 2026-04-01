"""Sidebar navigation."""
import streamlit as st


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
            "nurse": {"dashboard": "🏠 Dashboard",
                      "staff_session": "📋 Session & Queue",
                      "nurse_patients": "🏥 Patients",
                      "nurse_sessions": "📅 Sessions",
                      "nurse_emergency": "🚨 Emergency Book",
                      "chatbot": "🤖 AI Assistant"},
            "admin": {
                "admin_home": "🏠 Dashboard",
                "admin_queue": "📋 Session & Queue",
                "admin_staff": "👥 Staff",
                "admin_patients": "🏥 Patients",
                "admin_sessions_overview": "📅 Sessions",
                "admin_audit": "📜 Audit Logs",
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
