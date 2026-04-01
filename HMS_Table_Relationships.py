"""
Generate HMS Table Relationships PDF — shows every table, its PK, FKs,
and how they connect to each other.
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import (
    HexColor, white, black,
)
from reportlab.pdfgen import canvas
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

OUTPUT = "/sessions/hopeful-dreamy-ride/mnt/HMS/HMS_Table_Relationships.pdf"

# ─── Colours ──────────────────────────────────────────────
NAVY      = HexColor("#1e3a5f")
DARK_BLUE = HexColor("#2563eb")
LIGHT_BG  = HexColor("#f0f4ff")
HEADER_BG = HexColor("#1e3a5f")
PK_BG     = HexColor("#fef3c7")   # warm yellow for PK rows
FK_BG     = HexColor("#dbeafe")   # soft blue for FK rows
COL_BG    = HexColor("#f9fafb")   # grey for regular columns
WHITE     = white
BLACK     = black
GREEN     = HexColor("#059669")
RED       = HexColor("#dc2626")
ORANGE    = HexColor("#d97706")

# ─── Styles ───────────────────────────────────────────────
styles = getSampleStyleSheet()

title_style = ParagraphStyle(
    "Title2", parent=styles["Title"],
    fontSize=22, textColor=NAVY, spaceAfter=4*mm,
)
subtitle_style = ParagraphStyle(
    "Subtitle2", parent=styles["Normal"],
    fontSize=11, textColor=HexColor("#4b5563"), spaceAfter=8*mm,
)
heading_style = ParagraphStyle(
    "TblHeading", parent=styles["Heading2"],
    fontSize=14, textColor=NAVY, spaceBefore=6*mm, spaceAfter=2*mm,
)
section_style = ParagraphStyle(
    "SectionHead", parent=styles["Heading1"],
    fontSize=16, textColor=DARK_BLUE, spaceBefore=8*mm, spaceAfter=4*mm,
)
body_style = ParagraphStyle(
    "Body2", parent=styles["Normal"],
    fontSize=9.5, leading=13, textColor=HexColor("#374151"),
)
small_style = ParagraphStyle(
    "Small", parent=styles["Normal"],
    fontSize=8.5, leading=11, textColor=HexColor("#6b7280"),
)
cell_style = ParagraphStyle(
    "Cell", parent=styles["Normal"],
    fontSize=8.5, leading=11, textColor=BLACK,
)
cell_bold = ParagraphStyle(
    "CellBold", parent=cell_style,
    fontName="Helvetica-Bold",
)
cell_header = ParagraphStyle(
    "CellHeader", parent=cell_style,
    fontName="Helvetica-Bold", textColor=WHITE, fontSize=9,
)

# ─── Table Schema Data ────────────────────────────────────
# Each table: (name, description, columns_list)
# Each column: (name, type, PK/FK/-, FK_target_or_notes)

TABLES = [
    ("users", "Every person in the system (patients, doctors, nurses, admins)", [
        ("id", "UUID", "PK", "Primary Key"),
        ("email", "VARCHAR(255)", "-", "UNIQUE, NOT NULL"),
        ("phone", "VARCHAR(15)", "-", "Nullable (families share)"),
        ("password_hash", "VARCHAR(255)", "-", "NULL if Google OAuth"),
        ("full_name", "VARCHAR(255)", "-", "NOT NULL"),
        ("role", "VARCHAR(20)", "-", "patient / doctor / nurse / admin"),
        ("google_id", "VARCHAR(255)", "-", "UNIQUE, Google OAuth ID"),
        ("is_active", "BOOLEAN", "-", "Default true"),
        ("created_at", "TIMESTAMPTZ", "-", "Auto"),
        ("updated_at", "TIMESTAMPTZ", "-", "Auto-trigger"),
    ]),

    ("patients", "Medical profile. One user has exactly one patient record.", [
        ("id", "UUID", "PK", "Primary Key"),
        ("user_id", "UUID", "FK", "REFERENCES users(id) UNIQUE"),
        ("abha_id", "VARCHAR(14)", "-", "UHID, UNIQUE"),
        ("date_of_birth", "DATE", "-", "Used for priority_tier"),
        ("gender", "VARCHAR(10)", "-", "male / female / other"),
        ("blood_group", "VARCHAR(5)", "-", "A+, B-, O+, etc."),
        ("emergency_contact_name", "VARCHAR(255)", "-", "Nullable"),
        ("emergency_contact_phone", "VARCHAR(15)", "-", "Nullable"),
        ("address", "TEXT", "-", "Nullable"),
        ("risk_score", "DECIMAL(4,2)", "-", "Default 0.00, >=7 blocks"),
        ("created_at", "TIMESTAMPTZ", "-", "Auto"),
        ("updated_at", "TIMESTAMPTZ", "-", "Auto-trigger"),
    ]),

    ("doctors", "Doctor profile and consultation settings.", [
        ("id", "UUID", "PK", "Primary Key"),
        ("user_id", "UUID", "FK", "REFERENCES users(id) UNIQUE"),
        ("specialization", "VARCHAR(255)", "-", "e.g. Cardiology"),
        ("qualification", "VARCHAR(255)", "-", "e.g. MBBS, MD"),
        ("license_number", "VARCHAR(50)", "-", "UNIQUE, NOT NULL"),
        ("consultation_fee", "DECIMAL(10,2)", "-", "Fee in INR"),
        ("max_patients_per_slot", "INTEGER", "-", "Default 2"),
        ("is_available", "BOOLEAN", "-", "Master toggle"),
        ("created_at", "TIMESTAMPTZ", "-", "Auto"),
        ("updated_at", "TIMESTAMPTZ", "-", "Auto-trigger"),
    ]),

    ("patient_relationships", "Multi-beneficiary: who can book for whom.", [
        ("id", "UUID", "PK", "Primary Key"),
        ("booker_patient_id", "UUID", "FK", "REFERENCES patients(id)"),
        ("beneficiary_patient_id", "UUID", "FK", "REFERENCES patients(id)"),
        ("relationship_type", "VARCHAR(20)", "-", "self/spouse/child/parent/..."),
        ("is_approved", "BOOLEAN", "-", "Beneficiary must approve"),
        ("approved_at", "TIMESTAMPTZ", "-", "NULL until approved"),
        ("created_at", "TIMESTAMPTZ", "-", "Auto"),
    ]),

    ("sessions", "Doctor availability windows, divided into time slots.", [
        ("id", "UUID", "PK", "Primary Key"),
        ("doctor_id", "UUID", "FK", "REFERENCES doctors(id)"),
        ("session_date", "DATE", "-", "NOT NULL"),
        ("start_time", "TIME", "-", "NOT NULL"),
        ("end_time", "TIME", "-", "NOT NULL, > start_time"),
        ("slot_duration_minutes", "INTEGER", "-", "Default 15"),
        ("max_patients_per_slot", "INTEGER", "-", "Default 2"),
        ("scheduling_type", "VARCHAR(20)", "-", "TIME_SLOT/FCFS/PRIORITY_QUEUE"),
        ("total_slots", "INTEGER", "-", "Computed: (end-start)/duration"),
        ("booked_count", "INTEGER", "-", "Counter cache"),
        ("doctor_checkin_at", "TIMESTAMPTZ", "-", "When doctor starts"),
        ("delay_minutes", "INTEGER", "-", "Default 0"),
        ("status", "VARCHAR(20)", "-", "active/cancelled/completed"),
        ("created_at", "TIMESTAMPTZ", "-", "Auto"),
        ("updated_at", "TIMESTAMPTZ", "-", "Auto-trigger"),
    ]),

    ("appointments", "Core booking table. Lifecycle: booked -> checked_in -> in_progress -> completed.", [
        ("id", "UUID", "PK", "Primary Key"),
        ("session_id", "UUID", "FK", "REFERENCES sessions(id)"),
        ("patient_id", "UUID", "FK", "REFERENCES patients(id)  [beneficiary]"),
        ("booked_by_patient_id", "UUID", "FK", "REFERENCES patients(id)  [booker]"),
        ("slot_number", "INTEGER", "-", "Which slot (1 to total_slots)"),
        ("slot_position", "INTEGER", "-", "1=original, 2=overbook, 3=emergency"),
        ("priority_tier", "VARCHAR(10)", "-", "NORMAL / HIGH / CRITICAL"),
        ("visual_priority", "INTEGER", "-", "1-10, nurse sets at check-in"),
        ("is_emergency", "BOOLEAN", "-", "Default false"),
        ("status", "VARCHAR(20)", "-", "booked/checked_in/in_progress/..."),
        ("checked_in_at", "TIMESTAMPTZ", "-", "When patient checked in"),
        ("checked_in_by", "UUID", "FK", "REFERENCES users(id)  [nurse]"),
        ("completed_at", "TIMESTAMPTZ", "-", "When consult finished"),
        ("notes", "TEXT", "-", "Doctor notes post-consult"),
        ("created_at", "TIMESTAMPTZ", "-", "Auto"),
        ("updated_at", "TIMESTAMPTZ", "-", "Auto-trigger"),
    ]),

    ("waitlist", "When all slots are full, patient joins waitlist.", [
        ("id", "UUID", "PK", "Primary Key"),
        ("session_id", "UUID", "FK", "REFERENCES sessions(id)"),
        ("patient_id", "UUID", "FK", "REFERENCES patients(id)  [beneficiary]"),
        ("booked_by_patient_id", "UUID", "FK", "REFERENCES patients(id)  [booker]"),
        ("priority_tier", "VARCHAR(10)", "-", "NORMAL / HIGH / CRITICAL"),
        ("status", "VARCHAR(20)", "-", "waiting/promoted/expired/cancelled"),
        ("promoted_at", "TIMESTAMPTZ", "-", "When promoted to appointment"),
        ("created_at", "TIMESTAMPTZ", "-", "Auto"),
    ]),

    ("cancellation_log", "Immutable record of every cancellation.", [
        ("id", "UUID", "PK", "Primary Key"),
        ("appointment_id", "UUID", "FK", "REFERENCES appointments(id)"),
        ("cancelled_by_patient_id", "UUID", "FK", "REFERENCES patients(id)  [booker]"),
        ("reason", "TEXT", "-", "Nullable"),
        ("risk_delta", "DECIMAL(4,2)", "-", "Added to booker's risk_score"),
        ("hours_before_appointment", "DECIMAL(6,2)", "-", "Hours between cancel & appt"),
        ("created_at", "TIMESTAMPTZ", "-", "Auto"),
    ]),

    ("notification_log", "Tracks every notification sent (email, SMS, push).", [
        ("id", "UUID", "PK", "Primary Key"),
        ("user_id", "UUID", "FK", "REFERENCES users(id)"),
        ("appointment_id", "UUID", "FK", "REFERENCES appointments(id)  [nullable]"),
        ("type", "VARCHAR(30)", "-", "booking_confirmation/cancellation/..."),
        ("channel", "VARCHAR(10)", "-", "email / sms / push"),
        ("status", "VARCHAR(10)", "-", "pending / sent / failed"),
        ("content", "TEXT", "-", "NOT NULL"),
        ("error_message", "TEXT", "-", "If status=failed"),
        ("sent_at", "TIMESTAMPTZ", "-", "When actually sent"),
        ("created_at", "TIMESTAMPTZ", "-", "Auto"),
    ]),

    ("doctor_ratings", "Post-visit feedback. One rating per appointment.", [
        ("id", "UUID", "PK", "Primary Key"),
        ("appointment_id", "UUID", "FK", "REFERENCES appointments(id) UNIQUE"),
        ("patient_id", "UUID", "FK", "REFERENCES patients(id)"),
        ("doctor_id", "UUID", "FK", "REFERENCES doctors(id)"),
        ("rating", "INTEGER", "-", "1 to 5"),
        ("review", "TEXT", "-", "Free text review"),
        ("sentiment_score", "DECIMAL(3,2)", "-", "OpenAI: -1.0 to 1.0"),
        ("created_at", "TIMESTAMPTZ", "-", "Auto"),
    ]),

    ("booking_audit_log", "Complete audit trail. Never deleted.", [
        ("id", "UUID", "PK", "Primary Key"),
        ("action", "VARCHAR(20)", "-", "book/cancel/reschedule/check_in/..."),
        ("appointment_id", "UUID", "FK", "REFERENCES appointments(id) [nullable]"),
        ("performed_by_user_id", "UUID", "FK", "REFERENCES users(id)"),
        ("patient_id", "UUID", "FK", "REFERENCES patients(id) [nullable]"),
        ("metadata", "JSONB", "-", "Action-specific data"),
        ("ip_address", "INET", "-", "Nullable"),
        ("created_at", "TIMESTAMPTZ", "-", "Auto"),
    ]),

    ("scheduling_config", "System-wide config as key-value pairs.", [
        ("id", "UUID", "PK", "Primary Key"),
        ("config_key", "VARCHAR(100)", "-", "UNIQUE, NOT NULL"),
        ("config_value", "JSONB", "-", "NOT NULL"),
        ("description", "TEXT", "-", "Nullable"),
        ("updated_by", "UUID", "FK", "REFERENCES users(id) [nullable]"),
        ("created_at", "TIMESTAMPTZ", "-", "Auto"),
        ("updated_at", "TIMESTAMPTZ", "-", "Auto-trigger"),
    ]),
]

# ─── FK Relationship Summary ─────────────────────────────
RELATIONSHIPS = [
    ("patients.user_id", "users.id", "1:1", "Each patient IS a user"),
    ("doctors.user_id", "users.id", "1:1", "Each doctor IS a user"),
    ("patient_relationships.booker_patient_id", "patients.id", "N:1", "Booker"),
    ("patient_relationships.beneficiary_patient_id", "patients.id", "N:1", "Beneficiary"),
    ("sessions.doctor_id", "doctors.id", "N:1", "Doctor's availability window"),
    ("appointments.session_id", "sessions.id", "N:1", "Which session/time-block"),
    ("appointments.patient_id", "patients.id", "N:1", "Beneficiary (who sees doctor)"),
    ("appointments.booked_by_patient_id", "patients.id", "N:1", "Booker (who made the booking)"),
    ("appointments.checked_in_by", "users.id", "N:1", "Nurse who checked patient in"),
    ("waitlist.session_id", "sessions.id", "N:1", "Waiting for slot in this session"),
    ("waitlist.patient_id", "patients.id", "N:1", "Beneficiary"),
    ("waitlist.booked_by_patient_id", "patients.id", "N:1", "Booker"),
    ("cancellation_log.appointment_id", "appointments.id", "N:1", "Which appointment was cancelled"),
    ("cancellation_log.cancelled_by_patient_id", "patients.id", "N:1", "Who cancelled"),
    ("notification_log.user_id", "users.id", "N:1", "Who was notified"),
    ("notification_log.appointment_id", "appointments.id", "N:1", "Related appointment (nullable)"),
    ("doctor_ratings.appointment_id", "appointments.id", "1:1", "One rating per appointment"),
    ("doctor_ratings.patient_id", "patients.id", "N:1", "Who gave the rating"),
    ("doctor_ratings.doctor_id", "doctors.id", "N:1", "Who was rated"),
    ("booking_audit_log.appointment_id", "appointments.id", "N:1", "Audited appointment (nullable)"),
    ("booking_audit_log.performed_by_user_id", "users.id", "N:1", "Who performed the action"),
    ("booking_audit_log.patient_id", "patients.id", "N:1", "Affected patient (nullable)"),
    ("scheduling_config.updated_by", "users.id", "N:1", "Admin who changed config (nullable)"),
]

# ─── JOIN Chain examples ──────────────────────────────────
JOIN_CHAINS = [
    ("Get patient name from appointment",
     "appointments -> patients -> users",
     "JOIN patients p ON a.patient_id = p.id\nJOIN users u ON p.user_id = u.id"),
    ("Get doctor name from appointment",
     "appointments -> sessions -> doctors -> users",
     "JOIN sessions s ON a.session_id = s.id\nJOIN doctors d ON s.doctor_id = d.id\nJOIN users u ON d.user_id = u.id"),
    ("Get doctor name from session",
     "sessions -> doctors -> users",
     "JOIN doctors d ON s.doctor_id = d.id\nJOIN users u ON d.user_id = u.id"),
    ("Get who booked an appointment",
     "appointments -> patients (booker) -> users",
     "JOIN patients p ON a.booked_by_patient_id = p.id\nJOIN users u ON p.user_id = u.id"),
    ("Get patient's appointments with doctor names",
     "patients -> appointments -> sessions -> doctors -> users",
     "JOIN appointments a ON a.patient_id = p.id\nJOIN sessions s ON a.session_id = s.id\nJOIN doctors d ON s.doctor_id = d.id\nJOIN users u_d ON d.user_id = u_d.id"),
]


def build_pdf():
    doc = SimpleDocTemplate(
        OUTPUT, pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=15*mm, bottomMargin=15*mm,
    )
    story = []

    # ── Title Page Content ──
    story.append(Spacer(1, 15*mm))
    story.append(Paragraph("HMS Database — Table Relationships", title_style))
    story.append(Paragraph(
        "Primary keys, foreign keys, and how every table connects. "
        "12 tables total across GO (core) and LO (transaction) layers.",
        subtitle_style,
    ))
    story.append(Spacer(1, 4*mm))

    # ── SECTION 1: Relationship Summary ──
    story.append(Paragraph("1. All Foreign Key Relationships", section_style))
    story.append(Paragraph(
        "Every FK in the system. The 'From' column is the FK, 'To' is the PK it references. "
        "Cardinality shows 1:1 (one-to-one) or N:1 (many-to-one).",
        body_style,
    ))
    story.append(Spacer(1, 3*mm))

    # Build relationship table
    rel_data = [[
        Paragraph("<b>From (FK)</b>", cell_header),
        Paragraph("<b>To (PK)</b>", cell_header),
        Paragraph("<b>Card.</b>", cell_header),
        Paragraph("<b>Meaning</b>", cell_header),
    ]]
    for fk_col, pk_col, card, meaning in RELATIONSHIPS:
        rel_data.append([
            Paragraph(fk_col, cell_style),
            Paragraph(pk_col, cell_style),
            Paragraph(f"<b>{card}</b>", cell_style),
            Paragraph(meaning, cell_style),
        ])

    col_widths = [55*mm, 40*mm, 14*mm, 60*mm]
    rel_table = Table(rel_data, colWidths=col_widths, repeatRows=1)
    rel_styles = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    # Alternate row colours
    for i in range(1, len(rel_data)):
        if i % 2 == 0:
            rel_styles.append(("BACKGROUND", (0, i), (-1, i), LIGHT_BG))
    rel_table.setStyle(TableStyle(rel_styles))
    story.append(rel_table)

    # ── KEY INSIGHT BOX ──
    story.append(Spacer(1, 5*mm))
    insight_text = (
        "<b>Key Insight — No direct link between appointments and users!</b><br/>"
        "To get a patient name: appointments -> patients -> users (2 hops)<br/>"
        "To get a doctor name: appointments -> sessions -> doctors -> users (3 hops)<br/>"
        "This is because patients and doctors are ROLES of a user, not the user itself."
    )
    insight_style = ParagraphStyle(
        "Insight", parent=body_style,
        backColor=HexColor("#fef3c7"), borderPadding=8,
        fontSize=9, leading=13, textColor=HexColor("#92400e"),
    )
    story.append(Paragraph(insight_text, insight_style))

    story.append(PageBreak())

    # ── SECTION 2: Common JOIN Chains ──
    story.append(Paragraph("2. Common JOIN Chains", section_style))
    story.append(Paragraph(
        "These are the multi-hop JOINs you'll use most often. "
        "Remember: you can NEVER skip a table in the chain.",
        body_style,
    ))
    story.append(Spacer(1, 3*mm))

    for purpose, chain, sql in JOIN_CHAINS:
        join_block = []
        join_block.append(Paragraph(f"<b>{purpose}</b>", ParagraphStyle(
            "JoinTitle", parent=body_style,
            fontName="Helvetica-Bold", fontSize=10, textColor=NAVY,
            spaceBefore=3*mm,
        )))
        join_block.append(Paragraph(f"Chain: <b>{chain}</b>", small_style))
        # SQL in a shaded box
        sql_lines = sql.replace("\n", "<br/>")
        sql_style = ParagraphStyle(
            "SQL", parent=body_style,
            fontName="Courier", fontSize=8, leading=11,
            backColor=HexColor("#f1f5f9"), borderPadding=6,
            textColor=HexColor("#1e293b"),
        )
        join_block.append(Spacer(1, 1*mm))
        join_block.append(Paragraph(sql_lines, sql_style))
        join_block.append(Spacer(1, 2*mm))
        story.append(KeepTogether(join_block))

    story.append(PageBreak())

    # ── SECTION 3: All Tables Detail ──
    story.append(Paragraph("3. Table Details — All 12 Tables", section_style))

    for tbl_name, tbl_desc, columns in TABLES:
        tbl_block = []
        tbl_block.append(Paragraph(f"{tbl_name}", heading_style))
        tbl_block.append(Paragraph(tbl_desc, small_style))
        tbl_block.append(Spacer(1, 2*mm))

        # Table header
        data = [[
            Paragraph("<b>Column</b>", cell_header),
            Paragraph("<b>Type</b>", cell_header),
            Paragraph("<b>Key</b>", cell_header),
            Paragraph("<b>Notes</b>", cell_header),
        ]]
        row_colors = []
        for col_name, col_type, key_type, notes in columns:
            if key_type == "PK":
                key_display = Paragraph('<font color="#b45309"><b>PK</b></font>', cell_style)
                row_colors.append(PK_BG)
            elif key_type == "FK":
                key_display = Paragraph('<font color="#2563eb"><b>FK</b></font>', cell_style)
                row_colors.append(FK_BG)
            else:
                key_display = Paragraph("-", cell_style)
                row_colors.append(COL_BG)
            data.append([
                Paragraph(f"<b>{col_name}</b>", cell_style),
                Paragraph(col_type, cell_style),
                key_display,
                Paragraph(notes, cell_style),
            ])

        t = Table(data, colWidths=[38*mm, 32*mm, 12*mm, 88*mm], repeatRows=1)
        t_styles = [
            ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]
        for i, bg in enumerate(row_colors, start=1):
            t_styles.append(("BACKGROUND", (0, i), (-1, i), bg))
        t.setStyle(TableStyle(t_styles))

        tbl_block.append(t)
        tbl_block.append(Spacer(1, 4*mm))
        story.append(KeepTogether(tbl_block))

    # ── LEGEND ──
    story.append(Spacer(1, 6*mm))
    legend = (
        "<b>Legend:</b>  "
        '<font backColor="#fef3c7"> PK </font> = Primary Key  |  '
        '<font backColor="#dbeafe"> FK </font> = Foreign Key  |  '
        "1:1 = One-to-one  |  N:1 = Many-to-one"
    )
    story.append(Paragraph(legend, body_style))

    doc.build(story)
    print(f"PDF saved to {OUTPUT}")


if __name__ == "__main__":
    build_pdf()
