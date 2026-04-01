"""
Generate HMS Folder Structure & Dashboard Architecture PDF
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.enums import TA_LEFT, TA_CENTER

# Colors
NAVY = HexColor("#1e3a5f")
DARK_BLUE = HexColor("#2d5a8e")
LIGHT_BLUE = HexColor("#e8f4fd")
ACCENT = HexColor("#3b82f6")
GREEN = HexColor("#16a34a")
ORANGE = HexColor("#ea580c")
PURPLE = HexColor("#7c3aed")
RED = HexColor("#dc2626")
GRAY = HexColor("#6b7280")
LIGHT_GRAY = HexColor("#f3f4f6")
WHITE = HexColor("#ffffff")
BLACK = HexColor("#111827")
TEAL = HexColor("#0d9488")

def build_pdf():
    doc = SimpleDocTemplate(
        "/sessions/hopeful-dreamy-ride/mnt/HMS/HMS_Folder_Structure.pdf",
        pagesize=A4,
        topMargin=1.5*cm, bottomMargin=1.5*cm,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle("Title2", parent=styles["Title"], fontSize=22, textColor=NAVY, spaceAfter=4)
    subtitle_style = ParagraphStyle("Subtitle2", parent=styles["Normal"], fontSize=11, textColor=GRAY, spaceAfter=16)
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=16, textColor=NAVY, spaceBefore=18, spaceAfter=8,
                         borderWidth=0, borderColor=ACCENT, borderPadding=0)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=13, textColor=DARK_BLUE, spaceBefore=12, spaceAfter=6)
    body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=9.5, textColor=BLACK, leading=14)
    code_style = ParagraphStyle("Code", parent=styles["Normal"], fontSize=8.5, fontName="Courier",
                                 textColor=NAVY, leading=12, leftIndent=8)
    small = ParagraphStyle("Small", parent=styles["Normal"], fontSize=8.5, textColor=GRAY, leading=11)

    story = []

    # ── Title ──
    story.append(Paragraph("HMS — Project Architecture", title_style))
    story.append(Paragraph("Hospital Management System — Folder Structure, Dashboards & Tech Stack", subtitle_style))
    story.append(Spacer(1, 6))

    # ── Tech Stack ──
    story.append(Paragraph("Tech Stack", h1))
    tech_data = [
        ["Layer", "Technology", "Purpose"],
        ["Backend API", "FastAPI (Python)", "REST endpoints, JWT auth, role-based access"],
        ["Frontend", "Streamlit", "All 4 dashboards (patient, doctor, nurse, admin)"],
        ["Primary DB", "PostgreSQL", "12 tables — patients, appointments, sessions, etc."],
        ["Chat Storage", "MongoDB", "AI chatbot conversation history (persistent)"],
        ["Vector DB", "ChromaDB", "Patient review embeddings for RAG feedback search"],
        ["AI Agent", "OpenAI Agents SDK", "Multi-role chatbot with tools (GPT-4o)"],
        ["Embeddings", "OpenAI text-embedding-3-small", "Review text vectorization for semantic search"],
        ["Email", "Gmail API", "Appointment notifications (booking, cancel, reminder)"],
        ["Calendar", "Google Calendar API", "Appointment sync to patient's calendar"],
        ["Auth", "JWT + Google OAuth", "Login, registration, token-based sessions"],
    ]
    t = Table(tech_data, colWidths=[80, 140, 260])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, 1), (-1, -1), LIGHT_GRAY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GRAY]),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 12))

    # ── Folder Structure ──
    story.append(Paragraph("Folder Structure", h1))

    folders = [
        ("HMS/", "Root", ""),
        ("  main.py", "FastAPI server entry point", "Starts uvicorn, registers all routers"),
        ("  streamlit_app.py", "ALL dashboards (~5000 lines)", "Patient, Doctor, Nurse, Admin UI"),
        ("  config.py", "Settings loader", "Reads .env, provides get_settings()"),
        ("  database.py", "PostgreSQL setup", "SQLAlchemy engine, table definitions, CHECK constraints"),
        ("  dependencies.py", "Auth middleware", "JWT verification, require_role() decorator"),
        ("  seed_rag.py", "ChromaDB seeder", "One-time script to embed existing reviews"),
        ("", "", ""),
        ("  api/routes/", "Backend API Endpoints", ""),
        ("    auth.py", "Authentication", "Login, register, Google OAuth, JWT tokens"),
        ("    appointment.py", "Appointments", "Book, cancel, reassign, emergency booking"),
        ("    queue.py", "Queue management", "Check-in, call, complete, no-show, priority"),
        ("    session_mgmt.py", "Sessions", "Create, activate, deactivate, extend, complete"),
        ("    doctor.py", "Doctor listing", "Search, details, sessions by doctor"),
        ("    patient.py", "Patient profiles", "CRUD, family members, relationships"),
        ("    admin.py", "Admin operations", "Config, audit logs, user management"),
        ("    rating.py", "Ratings", "Submit, view, stats for doctor reviews"),
        ("    chat.py", "Chatbot endpoint", "Handles /chat messages, routes to AI agent"),
        ("", "", ""),
        ("  api/schemas/", "Pydantic Schemas", "Request/response validation"),
        ("    auth_schemas.py", "", "LoginRequest, RegisterRequest, TokenResponse"),
        ("    appointment_schemas.py", "", "BookRequest, AppointmentResponse"),
        ("    queue_schemas.py", "", "QueueEntry, CheckInRequest"),
        ("    session_schemas.py", "", "SessionCreate, SessionResponse"),
        ("    patient_schemas.py", "", "PatientProfile, FamilyMember"),
        ("    doctor_schemas.py", "", "DoctorResponse, DoctorDetail"),
        ("    chat_schemas.py", "", "ChatRequest, ChatResponse"),
        ("", "", ""),
        ("  go/models/", '"Get Operations" — Read-heavy models', ""),
        ("    user.py", "UserModel", "Login, roles, profile lookup"),
        ("    patient.py", "PatientModel", "Patient details, risk score, ABHA"),
        ("    doctor.py", "DoctorModel", "Doctor profile, availability, fees"),
        ("    session.py", "SessionModel", "Doctor sessions, slots, scheduling"),
        ("    patient_relationship.py", "RelationshipModel", "Family members, beneficiary links"),
        ("    scheduling_config.py", "ConfigModel", "System config (max bookings, slot duration)"),
        ("", "", ""),
        ("  go/services/", "Business Logic & AI", ""),
        ("    chat_agent.py", "AI Chatbot (~87KB)", "OpenAI Agents SDK, tools for all 4 roles"),
        ("    booking_service.py", "Booking flow", "Slot check, waitlist, limits, lunch break"),
        ("    notification_dispatcher.py", "Email notifications", "Booking/cancel/reminder/no-show emails + logging"),
        ("    email_service.py", "Email templates", "Gmail API, HTML email rendering"),
        ("    calendar_service.py", "Calendar sync", "Google Calendar event creation"),
        ("    rag_service.py", "RAG for feedback", "ChromaDB + OpenAI embeddings + sentiment"),
        ("    mongo_chat_store.py", "Chat persistence", "MongoDB session/message storage"),
        ("    user_service.py", "User creation", "Registration, patient record creation"),
        ("", "", ""),
        ("  lo/models/", '"Log Operations" — Write-heavy models', ""),
        ("    appointment.py", "AppointmentModel", "Booking, slot positions, status transitions"),
        ("    waitlist.py", "WaitlistModel", "Waitlist entries, promotion logic"),
        ("    doctor_rating.py", "DoctorRatingModel", "Star ratings + text reviews"),
        ("    notification_log.py", "NotificationModel", "Email send log (pending/sent/failed)"),
        ("    booking_audit_log.py", "AuditModel", "All booking actions audit trail"),
        ("    cancellation_log.py", "CancellationModel", "Cancellation reasons + risk penalties"),
        ("", "", ""),
        ("  streamlit_pages/", "Streamlit Helpers", ""),
        ("    api_client.py", "HTTP client wrapper", "Streamlit -> FastAPI API calls"),
        ("", "", ""),
        ("  migrations/", "DB Migrations", "Schema change scripts (SQL)"),
    ]

    folder_data = [["Path", "Name / Purpose", "Details"]]
    for path, purpose, detail in folders:
        if path == "" and purpose == "":
            folder_data.append(["", "", ""])
        else:
            folder_data.append([path, purpose, detail])

    t2 = Table(folder_data, colWidths=[130, 140, 210])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("FONTNAME", (0, 1), (0, -1), "Courier"),
        ("TEXTCOLOR", (0, 1), (0, -1), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GRAY]),
        ("GRID", (0, 0), (-1, 0), 0.5, HexColor("#d1d5db")),
        ("LINEBELOW", (0, 0), (-1, 0), 1, NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))

    # Add light lines between rows (not thick grid)
    for i in range(1, len(folder_data)):
        if folder_data[i][0] == "" and folder_data[i][1] == "":
            t2.setStyle(TableStyle([
                ("LINEBELOW", (0, i), (-1, i), 0.8, ACCENT),
            ]))
        else:
            t2.setStyle(TableStyle([
                ("LINEBELOW", (0, i), (-1, i), 0.3, HexColor("#e5e7eb")),
            ]))

    story.append(t2)
    story.append(PageBreak())

    # ── Dashboards ──
    story.append(Paragraph("Dashboards (by Role)", h1))
    story.append(Paragraph(
        "All dashboards live in <b>streamlit_app.py</b>. After login, the system detects the user's role and renders the matching dashboard. "
        "Each role also has an <b>AI chatbot</b> with role-specific tools.",
        body
    ))
    story.append(Spacer(1, 10))

    dashboards = [
        ("Patient Dashboard", "#16a34a", [
            ["Section", "Features"],
            ["My Appointments", "View all bookings (self + family), status, slot time, doctor"],
            ["Book Appointment", "Search by specialty, pick doctor, choose session/slot, confirm"],
            ["Cancel / Undo", "Cancel with reason (affects risk score), undo within window"],
            ["Reschedule", "Move to different time slot (same or different session)"],
            ["Family Members", "Add/edit relatives, book on their behalf"],
            ["Ratings", "Rate completed appointments (1-5 stars + review)"],
            ["AI Chatbot", "Natural language booking, cancellation, family lookup, doctor search"],
        ]),
        ("Doctor Dashboard", "#3b82f6", [
            ["Section", "Features"],
            ["Live Queue", "Current patients, call next, mark complete, priority flags"],
            ["My Sessions", "Today's sessions, patient count, delay management"],
            ["Session Controls", "Activate, deactivate, update delay, extend, complete"],
            ["Patient Details", "Full profile, history, emergency contacts, risk score"],
            ["Emergency", "Flag patients as emergency, change priority tier"],
            ["Ratings", "View own ratings, search patient feedback (RAG)"],
            ["AI Chatbot", "Queue management, patient lookup, booking, session control"],
        ]),
        ("Nurse Dashboard", "#ea580c", [
            ["Section", "Features"],
            ["Queue Management", "Check-in, call, complete, no-show, undo actions"],
            ["Emergency Handling", "Emergency register + book, priority escalation"],
            ["Session Controls", "Create, activate, deactivate, extend, complete sessions"],
            ["Patient Search", "Find patients, view details, edit profiles"],
            ["Booking", "Staff book, register + book walk-ins, reassign appointments"],
            ["Operations Board", "All sessions across departments, slot availability"],
            ["AI Chatbot", "All nurse capabilities via natural language"],
        ]),
        ("Admin Dashboard", "#7c3aed", [
            ["Section", "Features"],
            ["Everything Nurses Have", "Queue, sessions, booking, operations board"],
            ["Doctor Management", "Add/edit doctors, set availability, manage schedules"],
            ["User Management", "All users, roles, status, registration"],
            ["System Config", "Max bookings/day, slot duration, risk thresholds"],
            ["Audit Logs", "Full trail of all booking actions (who did what when)"],
            ["Notification Log", "Email send status (pending/sent/failed)"],
            ["Analytics", "Doctor ratings, patient feedback (RAG search)"],
            ["AI Chatbot", "Full admin capabilities + config management"],
        ]),
    ]

    for name, color, data in dashboards:
        col = HexColor(color)
        story.append(Paragraph(f'<font color="{color}">{name}</font>', h2))
        t = Table(data, colWidths=[120, 360])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), col),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GRAY]),
            ("GRID", (0, 0), (-1, -1), 0.4, HexColor("#d1d5db")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(t)
        story.append(Spacer(1, 10))

    story.append(PageBreak())

    # ── AI Chatbot Architecture ──
    story.append(Paragraph("AI Chatbot Architecture", h1))
    story.append(Paragraph(
        "Single agent per role — no sub-agents, no handoffs. Each role gets different tools and prompt instructions. "
        "The agent uses OpenAI Agents SDK with GPT-4o and stores conversations in MongoDB.",
        body
    ))
    story.append(Spacer(1, 8))

    chat_data = [
        ["Component", "Technology", "Details"],
        ["Agent Framework", "OpenAI Agents SDK", "function_tool decorators, RunContextWrapper"],
        ["LLM", "GPT-4o", "Via OpenAI API"],
        ["Chat Storage", "MongoDB", "2 collections: chat_sessions + chat_messages"],
        ["Session Management", "MongoSession + CompactionSession", "Persistent history, auto-compaction"],
        ["Embeddings", "text-embedding-3-small", "Review vectorization for RAG"],
        ["Vector Store", "ChromaDB (on-disk)", "Cosine similarity, doctor_reviews collection"],
        ["Sentiment", "GPT-4o-mini", "Review sentiment scoring (-1.0 to 1.0)"],
    ]
    t = Table(chat_data, colWidths=[110, 140, 230])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GRAY]),
        ("GRID", (0, 0), (-1, -1), 0.4, HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 14))

    # ── Tools by Role ──
    story.append(Paragraph("Chatbot Tools by Role", h2))

    tools_data = [
        ["Tool", "Patient", "Doctor", "Nurse", "Admin"],
        ["list_doctors / list_departments", "Y", "Y", "Y", "Y"],
        ["get_doctor_sessions", "Y", "Y", "Y", "Y"],
        ["get_operations_board", "Y", "Y", "Y", "Y"],
        ["book_appointment", "Y", "", "", ""],
        ["cancel_appointment", "Y", "", "", ""],
        ["undo_cancel_appointment", "Y", "", "", ""],
        ["reassign_appointment", "Y", "Y", "Y", "Y"],
        ["get_my_appointments", "Y", "", "", ""],
        ["get_my_profile / relationships", "Y", "", "", ""],
        ["get_queue / get_emergency", "", "Y", "Y", "Y"],
        ["checkin / call / complete", "", "Y", "Y", "Y"],
        ["mark_no_show / undo actions", "", "Y", "Y", "Y"],
        ["set_patient_priority", "", "Y", "Y", "Y"],
        ["staff_book / register_and_book", "", "Y", "Y", "Y"],
        ["emergency_book / emergency_register", "", "Y", "Y", "Y"],
        ["staff_cancel_appointment", "", "Y", "Y", "Y"],
        ["create / activate / deactivate session", "", "Y", "Y", "Y"],
        ["search_patients / patient_details", "", "Y", "Y", "Y"],
        ["update_patient_details", "", "Y", "", "Y"],
        ["submit_rating", "Y", "", "", ""],
        ["get_doctor_ratings / stats", "Y", "Y", "Y", "Y"],
        ["search_feedback (RAG)", "Y", "Y", "Y", "Y"],
        ["admin_get_audit / config", "", "", "", "Y"],
        ["admin_update_config", "", "", "", "Y"],
        ["admin_list_sessions", "", "", "", "Y"],
    ]
    t = Table(tools_data, colWidths=[170, 55, 55, 55, 55])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GRAY]),
        ("GRID", (0, 0), (-1, -1), 0.4, HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))
    # Color the Y cells green
    for r in range(1, len(tools_data)):
        for c in range(1, 5):
            if tools_data[r][c] == "Y":
                t.setStyle(TableStyle([
                    ("TEXTCOLOR", (c, r), (c, r), GREEN),
                    ("FONTNAME", (c, r), (c, r), "Helvetica-Bold"),
                ]))
    story.append(t)
    story.append(Spacer(1, 14))

    # ── Database Overview ──
    story.append(Paragraph("Database Tables (PostgreSQL)", h2))
    db_data = [
        ["Table", "Key Fields", "Purpose"],
        ["users", "id, email, role, full_name", "All system users (patient/doctor/nurse/admin)"],
        ["patients", "id, user_id, risk_score, abha_id", "Patient-specific data, linked to users"],
        ["doctors", "id, user_id, specialization, fee", "Doctor profiles, linked to users"],
        ["sessions", "id, doctor_id, date, start, end", "Doctor time slots (morning/afternoon)"],
        ["appointments", "id, session_id, patient_id, slot", "Individual bookings within sessions"],
        ["patient_relationships", "booker_id, beneficiary_id", "Family member links for proxy booking"],
        ["waitlist", "id, session_id, patient_id", "Overflow queue when slots are full"],
        ["doctor_ratings", "id, doctor_id, rating, review", "Patient feedback (1-5 stars + text)"],
        ["notification_log", "id, appointment_id, type, status", "Email notification tracking"],
        ["booking_audit_log", "id, action, performed_by", "Full audit trail of all actions"],
        ["cancellation_log", "id, appointment_id, reason", "Cancellation records + risk penalties"],
        ["scheduling_config", "key, value", "System-wide config parameters"],
    ]
    t = Table(db_data, colWidths=[120, 150, 210])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 1), (0, -1), "Courier"),
        ("TEXTCOLOR", (0, 1), (0, -1), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GRAY]),
        ("GRID", (0, 0), (-1, -1), 0.4, HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)

    # Build
    doc.build(story)
    print("PDF generated: HMS_Folder_Structure.pdf")

if __name__ == "__main__":
    build_pdf()
