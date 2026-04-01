"""Login and authentication pages."""
import streamlit as st
from streamlit_pages import api_client as api


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
