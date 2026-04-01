"""Chat interface powered by AI assistant."""
import streamlit as st
from streamlit_pages import api_client as api

# ── Hands-free voice component (Web Speech API) ──────────────
import streamlit.components.v1 as _stc
import os
_VOICE_COMPONENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "components", "voice_input")
_voice_input = _stc.declare_component("voice_input", path=_VOICE_COMPONENT_DIR)

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
    # Uses the clean UI history collection (not the SDK's internal session data)
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
    col1, col2, col3, col4, col5 = st.columns([4, 1.5, 1.5, 1.5, 1.5])
    with col1:
        mode_label = "Booking" if st.session_state.chat_mode == "book" else "Chat"
        st.caption(f"Chatting as **{user['full_name']}** ({role.upper()}) — {mode_label} mode")
    with col2:
        # Voice mode toggle (hands-free Web Speech API — works in Chrome/Edge)
        voice_label = "🔊 Voice On" if st.session_state.voice_mode else "🔇 Voice Off"
        if st.button(voice_label, use_container_width=True, key="toggle_voice"):
            st.session_state.voice_mode = not st.session_state.voice_mode
            st.rerun()
    with col3:
        if st.button("🗑 Clear Chat", use_container_width=True):
            # Clear messages on screen AND server-side history
            try:
                api.chat_clear()
            except Exception:
                pass
            st.session_state.chat_messages = []
            st.session_state.pop("chat_history_loaded", None)
            st.rerun()
    with col4:
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
    with col5:
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
    if st.session_state.voice_mode:
        # Hands-free mode: Web Speech API (Chrome/Edge) — no tap needed per message
        _voice_result = _voice_input(
            auto_start=True,
            resume=True,
            key="voice_input",
            default=None,
        )
        if _voice_result and isinstance(_voice_result, dict) and _voice_result.get("transcript"):
            _vts = _voice_result.get("ts", 0)
            if _vts != st.session_state.get("_last_voice_ts"):
                st.session_state._last_voice_ts = _vts
                _vtxt = _voice_result["transcript"].strip()
                if _vtxt:
                    st.caption(f'🗣️ *"{_vtxt}"*')
                    _send_and_reply(_vtxt, speak=True)
                    st.rerun()

    # ── Text input (always available) ──
    if prompt := st.chat_input("Type your message..."):
        _send_and_reply(prompt, speak=st.session_state.voice_mode)
        st.rerun()


# ════════════════════════════════════════════════════════════
# DASHBOARD ROUTER
# ════════════════════════════════════════════════════════════

