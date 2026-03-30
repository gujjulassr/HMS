"""
Admin API Routes — full system control.

Admin = developer-level access:
  - User management (create/edit/deactivate staff & doctors)
  - Doctor management (toggle availability, update settings)
  - System config (scheduling_config key-value store)
  - Audit log viewer
  - Dashboard stats (today's numbers at a glance)
  - Patient management (view/search, reset risk scores)
  - Session overview (all sessions across all doctors)
"""
from uuid import UUID
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import require_role
from go.models.user import User, UserModel
from go.models.doctor import Doctor, DoctorModel
from go.models.patient import PatientModel
from go.models.scheduling_config import ConfigModel
from go.services.user_service import hash_password

router = APIRouter()


# ═══════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════

class CreateStaffRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    phone: Optional[str] = None
    password: str = Field(min_length=6)
    role: str = Field(description="doctor, nurse, or admin")
    # Doctor-specific (required if role == 'doctor')
    specialization: Optional[str] = None
    qualification: Optional[str] = None
    license_number: Optional[str] = None
    consultation_fee: Optional[float] = 500.0
    max_patients_per_slot: Optional[int] = 2


class UpdateUserRequest(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None


class UpdateDoctorRequest(BaseModel):
    specialization: Optional[str] = None
    qualification: Optional[str] = None
    consultation_fee: Optional[float] = None
    max_patients_per_slot: Optional[int] = None
    is_available: Optional[bool] = None
    # full_name: Optional[str] = None 


class UpdateConfigRequest(BaseModel):
    value: object  # can be any JSON-serializable value
    description: Optional[str] = None


class ResetRiskRequest(BaseModel):
    patient_id: str
    new_score: float = 0.0


# ═══════════════════════════════════════════════════════════
# DASHBOARD STATS
# ═══════════════════════════════════════════════════════════

@router.get("/stats")
async def get_dashboard_stats(
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Today's numbers at a glance."""
    today = date.today()

    # Sessions today
    sess = await db.execute(
        text("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status = 'active') AS active,
                COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                COUNT(*) FILTER (WHERE status = 'inactive') AS inactive,
                COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled
            FROM sessions WHERE session_date = :today
        """),
        {"today": today},
    )
    s = sess.mappings().first()

    # Appointments today
    appt = await db.execute(
        text("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE a.status = 'booked') AS booked,
                COUNT(*) FILTER (WHERE a.status = 'checked_in') AS checked_in,
                COUNT(*) FILTER (WHERE a.status = 'in_progress') AS in_progress,
                COUNT(*) FILTER (WHERE a.status = 'completed') AS completed,
                COUNT(*) FILTER (WHERE a.status = 'no_show') AS no_show,
                COUNT(*) FILTER (WHERE a.status = 'cancelled') AS cancelled,
                COUNT(*) FILTER (WHERE a.is_emergency = true) AS emergencies
            FROM appointments a
            JOIN sessions s ON a.session_id = s.id
            WHERE s.session_date = :today
        """),
        {"today": today},
    )
    a = appt.mappings().first()

    # Users summary
    users = await db.execute(
        text("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE role = 'patient') AS patients,
                COUNT(*) FILTER (WHERE role = 'doctor') AS doctors,
                COUNT(*) FILTER (WHERE role = 'nurse') AS nurses,
                COUNT(*) FILTER (WHERE role = 'admin') AS admins,
                COUNT(*) FILTER (WHERE is_active = false) AS deactivated
            FROM users
        """)
    )
    u = users.mappings().first()

    # Active doctors today (have active sessions)
    active_docs = await db.execute(
        text("""
            SELECT COUNT(DISTINCT s.doctor_id) AS count
            FROM sessions s WHERE s.session_date = :today AND s.status = 'active'
        """),
        {"today": today},
    )
    ad = active_docs.scalar()

    # High risk patients
    high_risk = await db.execute(
        text("SELECT COUNT(*) FROM patients WHERE risk_score >= 7.0")
    )
    hr = high_risk.scalar()

    return {
        "date": str(today),
        "sessions": dict(s),
        "appointments": dict(a),
        "users": dict(u),
        "active_doctors_today": ad,
        "high_risk_patients": hr,
    }


# ═══════════════════════════════════════════════════════════
# USER MANAGEMENT
# ═══════════════════════════════════════════════════════════

@router.get("/users")
async def list_users(
    role: Optional[str] = Query(None, description="Filter by role"),
    specialization: Optional[str] = Query(None, description="Filter doctors by department"),
    include_inactive: bool = Query(False),
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """List all users, optionally filtered by role and department."""
    conditions = []
    params = {}
    joins = ""
    if role:
        conditions.append("u.role = :role")
        params["role"] = role
    if not include_inactive:
        conditions.append("u.is_active = true")
    if specialization:
        joins = "LEFT JOIN doctors d ON u.id = d.user_id"
        conditions.append("d.specialization = :spec")
        params["spec"] = specialization

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    result = await db.execute(
        text(f"""
            SELECT u.id, u.email, u.phone, u.full_name, u.role, u.is_active,
                   u.created_at, u.updated_at
            FROM users u
            {joins}
            {where}
            ORDER BY u.role, u.full_name
        """),
        params,
    )
    rows = result.mappings().all()
    return [{k: str(v) if v is not None else None for k, v in r.items()} for r in rows]


@router.post("/users")
async def create_staff_user(
    body: CreateStaffRequest,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new staff user (doctor, nurse, or admin)."""
    if body.role not in ("doctor", "nurse", "admin"):
        raise HTTPException(400, "Role must be doctor, nurse, or admin")

    # Check duplicate email
    existing = await db.execute(
        text("SELECT id FROM users WHERE email = :email"),
        {"email": body.email},
    )
    if existing.first():
        raise HTTPException(400, f"Email {body.email} already exists")

    # Create user
    new_user = await UserModel.create(
        db,
        email=body.email,
        full_name=body.full_name,
        role=body.role,
        password_hash=hash_password(body.password),
        phone=body.phone,
    )

    doctor_id = None
    # If doctor, create doctor profile
    if body.role == "doctor":
        if not body.specialization or not body.qualification or not body.license_number:
            raise HTTPException(400, "Doctor requires specialization, qualification, and license_number")
        doctor = await DoctorModel.create(
            db,
            user_id=new_user.id,
            specialization=body.specialization,
            qualification=body.qualification,
            license_number=body.license_number,
            consultation_fee=body.consultation_fee or 500.0,
            max_patients_per_slot=body.max_patients_per_slot or 2,
        )
        doctor_id = str(doctor.id)

    await db.commit()

    return {
        "user_id": str(new_user.id),
        "doctor_id": doctor_id,
        "email": new_user.email,
        "full_name": new_user.full_name,
        "role": new_user.role,
        "message": f"{body.role.title()} '{body.full_name}' created successfully",
    }


@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Update user details."""
    fields = {k: v for k, v in body.dict().items() if v is not None}
    if not fields:
        raise HTTPException(400, "No fields to update")

    updated = await UserModel.update(db, UUID(user_id), **fields)
    if not updated:
        raise HTTPException(404, "User not found")
    await db.commit()
    return {"message": "User updated", "user_id": user_id}


@router.put("/users/{user_id}/toggle")
async def toggle_user(
    user_id: str,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Toggle user active/inactive."""
    target = await db.execute(
        text("SELECT is_active FROM users WHERE id = :id"),
        {"id": UUID(user_id)},
    )
    row = target.first()
    if not row:
        raise HTTPException(404, "User not found")

    new_status = not row[0]
    await db.execute(
        text("UPDATE users SET is_active = :active WHERE id = :id"),
        {"id": UUID(user_id), "active": new_status},
    )
    await db.commit()
    return {"user_id": user_id, "is_active": new_status,
            "message": f"User {'activated' if new_status else 'deactivated'}"}


# ═══════════════════════════════════════════════════════════
# DOCTOR MANAGEMENT
# ═══════════════════════════════════════════════════════════

@router.get("/departments")
async def list_departments(
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """List all unique departments (specializations)."""
    result = await db.execute(
        text("SELECT DISTINCT specialization FROM doctors ORDER BY specialization")
    )
    return [r[0] for r in result.all()]


@router.get("/doctors")
async def list_all_doctors(
    specialization: Optional[str] = Query(None, description="Filter by department"),
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """List all doctors with their user info."""
    conditions = []
    params = {}
    if specialization:
        conditions.append("d.specialization = :spec")
        params["spec"] = specialization

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    result = await db.execute(
        text(f"""
            SELECT d.id AS doctor_id, d.user_id, d.specialization, d.qualification,
                   d.license_number, d.consultation_fee, d.max_patients_per_slot,
                   d.is_available, d.created_at,
                   u.full_name, u.email, u.phone, u.is_active AS user_active
            FROM doctors d
            JOIN users u ON d.user_id = u.id
            {where}
            ORDER BY d.specialization, u.full_name
        """),
        params,
    )
    return [{k: str(v) if v is not None else None for k, v in r.items()} for r in result.mappings().all()]


@router.put("/doctors/{doctor_id}")
async def update_doctor(
    doctor_id: str,
    body: UpdateDoctorRequest,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Update doctor settings."""
    fields = {k: v for k, v in body.dict().items() if v is not None}
    if not fields:
        raise HTTPException(400, "No fields to update")

    set_parts = []
    params = {"id": UUID(doctor_id)}
    for k, v in fields.items():
        set_parts.append(f"{k} = :{k}")
        params[k] = v

    result = await db.execute(
        text(f"UPDATE doctors SET {', '.join(set_parts)} WHERE id = :id RETURNING *"),
        params,
    )
    if not result.first():
        raise HTTPException(404, "Doctor not found")
    await db.commit()
    return {"message": "Doctor updated", "doctor_id": doctor_id}


# ═══════════════════════════════════════════════════════════
# SYSTEM CONFIGURATION
# ═══════════════════════════════════════════════════════════

@router.get("/config")
async def get_all_config(
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Get all scheduling config key-value pairs."""
    result = await db.execute(
        text("SELECT config_key, config_value, description, updated_at FROM scheduling_config ORDER BY config_key")
    )
    return [{k: str(v) if v is not None else None for k, v in r.items()} for r in result.mappings().all()]


@router.put("/config/{key}")
async def update_config(
    key: str,
    body: UpdateConfigRequest,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Update a config value."""
    updated = await ConfigModel.update_value(db, key, body.value, user.id)
    if not updated:
        raise HTTPException(404, f"Config key '{key}' not found")
    await db.commit()
    return {"message": f"Config '{key}' updated", "key": key, "value": body.value}


# ═══════════════════════════════════════════════════════════
# AUDIT LOGS
# ═══════════════════════════════════════════════════════════

@router.get("/audit")
async def get_audit_logs(
    action: Optional[str] = Query(None, description="Filter by action type"),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Query the booking audit log."""
    conditions = []
    params = {"limit": limit, "offset": offset}

    if action:
        conditions.append("bal.action = :action")
        params["action"] = action
    if from_date:
        conditions.append("bal.created_at >= :from_date")
        params["from_date"] = datetime.combine(date.fromisoformat(from_date), datetime.min.time())
    if to_date:
        from datetime import timedelta
        conditions.append("bal.created_at < :to_date_end")
        params["to_date_end"] = datetime.combine(date.fromisoformat(to_date) + timedelta(days=1), datetime.min.time())

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    try:
        result = await db.execute(
            text(f"""
                SELECT bal.id, bal.action, bal.appointment_id, bal.patient_id,
                       bal.performed_by_user_id, bal.metadata, bal.ip_address, bal.created_at,
                       u.full_name AS performed_by_name,
                       pu.full_name AS patient_name
                FROM booking_audit_log bal
                LEFT JOIN users u ON bal.performed_by_user_id = u.id
                LEFT JOIN patients p ON bal.patient_id = p.id
                LEFT JOIN users pu ON p.user_id = pu.id
                {where}
                ORDER BY bal.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.mappings().all()

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM booking_audit_log bal {where}"),
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
        total = count_result.scalar()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("Audit query failed")
        # Table might not exist yet — return empty
        return {"total": 0, "logs": [], "error": str(exc)}

    import json as _json
    serialized = []
    for r in rows:
        d = {}
        for k, v in r.items():
            if k == "metadata":
                if isinstance(v, dict):
                    d[k] = v
                elif isinstance(v, str):
                    try:
                        d[k] = _json.loads(v)
                    except (ValueError, TypeError):
                        d[k] = v
                else:
                    d[k] = v
            elif v is not None:
                d[k] = str(v)
            else:
                d[k] = None
        serialized.append(d)
    return {"total": total, "logs": serialized}


# ═══════════════════════════════════════════════════════════
# PATIENT MANAGEMENT
# ═══════════════════════════════════════════════════════════

@router.get("/patients")
async def list_patients(
    search: Optional[str] = Query(None, description="Search by name or phone"),
    high_risk_only: bool = Query(False),
    include_inactive: bool = Query(False, description="Include deactivated patients"),
    specialization: Optional[str] = Query(None, description="Filter by department"),
    doctor_id: Optional[str] = Query(None, description="Filter by doctor"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    user: User = Depends(require_role("admin", "nurse")),
    db: AsyncSession = Depends(get_db),
):
    """List patients with full details, filterable by department/doctor. Accessible by admin and nurse."""
    conditions = [] if include_inactive else ["u.is_active = true"]
    params = {"limit": limit, "offset": offset}
    joins = ""

    if search:
        conditions.append("(u.full_name ILIKE :search OR u.phone ILIKE :search OR u.email ILIKE :search OR COALESCE(p.abha_id, '') ILIKE :search)")
        params["search"] = f"%{search}%"
    if high_risk_only:
        conditions.append("p.risk_score >= 7.0")
    if specialization or doctor_id:
        joins = """
            JOIN appointments a2 ON a2.patient_id = p.id
            JOIN sessions s2 ON a2.session_id = s2.id
            JOIN doctors d2 ON s2.doctor_id = d2.id
        """
        if specialization:
            conditions.append("d2.specialization = :spec")
            params["spec"] = specialization
        if doctor_id:
            conditions.append("d2.id = :doc_id")
            params["doc_id"] = UUID(doctor_id)

    where = "WHERE " + " AND ".join(conditions)
    distinct = "DISTINCT" if (specialization or doctor_id) else ""

    result = await db.execute(
        text(f"""
            SELECT {distinct} p.id AS patient_id, p.user_id, p.abha_id, p.date_of_birth,
                   p.gender, p.blood_group, p.risk_score, p.address,
                   p.emergency_contact_name, p.emergency_contact_phone,
                   u.full_name, u.email, u.phone, u.is_active, u.created_at,
                   (SELECT COUNT(*) FROM appointments a WHERE a.patient_id = p.id) AS total_appointments,
                   (SELECT COUNT(*) FROM appointments a WHERE a.patient_id = p.id AND a.status = 'no_show') AS no_shows
            FROM patients p
            JOIN users u ON p.user_id = u.id
            {joins}
            {where}
            ORDER BY p.risk_score DESC, u.full_name
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    return [{k: str(v) if v is not None else None for k, v in r.items()} for r in result.mappings().all()]


@router.put("/patients/{patient_id}/reset-risk")
async def reset_patient_risk(
    patient_id: str,
    body: ResetRiskRequest,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Reset a patient's risk score (admin override)."""
    result = await db.execute(
        text("UPDATE patients SET risk_score = :score WHERE id = :id RETURNING id"),
        {"id": UUID(patient_id), "score": body.new_score},
    )
    if not result.first():
        raise HTTPException(404, "Patient not found")
    await db.commit()
    return {"message": f"Risk score reset to {body.new_score}", "patient_id": patient_id}


@router.get("/patients/{patient_id}")
async def get_patient_detail(
    patient_id: str,
    user: User = Depends(require_role("admin", "nurse", "doctor")),
    db: AsyncSession = Depends(get_db),
):
    """Get full patient details including profile, relationships, and appointments. Accessible by staff."""
    pid = UUID(patient_id)

    # Patient + user profile
    profile = await db.execute(
        text("""
            SELECT p.id AS patient_id, u.id AS user_id,
                   p.abha_id, p.date_of_birth, p.gender,
                   p.blood_group, p.risk_score, p.address,
                   p.emergency_contact_name, p.emergency_contact_phone,
                   u.full_name, u.email, u.phone, u.is_active, u.created_at
            FROM patients p JOIN users u ON p.user_id = u.id
            WHERE p.id = :pid
        """),
        {"pid": pid},
    )
    row = profile.mappings().first()
    if not row:
        raise HTTPException(404, "Patient not found")
    patient_data = {k: str(v) if v is not None else None for k, v in row.items()}

    # Appointments (recent 20)
    appts = await db.execute(
        text("""
            SELECT a.id AS appointment_id, a.status, a.slot_number,
                   a.checked_in_at, a.completed_at, a.notes,
                   s.session_date, s.start_time, s.end_time,
                   s.slot_duration_minutes,
                   u_d.full_name AS doctor_name, d.specialization
            FROM appointments a
            JOIN sessions s ON a.session_id = s.id
            JOIN doctors d ON s.doctor_id = d.id
            JOIN users u_d ON d.user_id = u_d.id
            WHERE a.patient_id = :pid
            ORDER BY s.session_date DESC, s.start_time DESC
            LIMIT 20
        """),
        {"pid": pid},
    )
    appt_list = []
    for r in appts.mappings().all():
        row_dict = {k: str(v) if v is not None else None for k, v in r.items()}
        # Compute slot-specific time from session start + (slot - 1) * duration
        try:
            st_val = r["start_time"]
            dur = r["slot_duration_minutes"] or 15
            slot = r["slot_number"]
            hh = st_val.hour if hasattr(st_val, "hour") else int(str(st_val)[:2])
            mm = st_val.minute if hasattr(st_val, "minute") else int(str(st_val)[3:5])
            total_min = hh * 60 + mm + (slot - 1) * dur
            row_dict["slot_time"] = f"{total_min // 60:02d}:{total_min % 60:02d}"
        except Exception:
            row_dict["slot_time"] = None
        appt_list.append(row_dict)

    # Family relationships
    rels = await db.execute(
        text("""
            SELECT pr.relationship_type, pr.is_approved,
                   u_b.full_name AS beneficiary_name, p_b.id AS beneficiary_patient_id
            FROM patient_relationships pr
            JOIN patients p_b ON pr.beneficiary_patient_id = p_b.id
            JOIN users u_b ON p_b.user_id = u_b.id
            WHERE pr.booker_patient_id = :pid AND pr.relationship_type != 'self'
        """),
        {"pid": pid},
    )
    rel_list = [{k: str(v) if v is not None else None for k, v in r.items()} for r in rels.mappings().all()]

    return {**patient_data, "appointments": appt_list, "relationships": rel_list}


@router.put("/patients/{patient_id}/update")
async def admin_update_patient(
    patient_id: str,
    body: dict,
    user: User = Depends(require_role("admin", "nurse", "doctor")),
    db: AsyncSession = Depends(get_db),
):
    """Staff can update patient profile fields (name, email, phone, etc)."""
    pid = UUID(patient_id)

    # ── Verify patient exists first ──
    check = await db.execute(
        text("SELECT p.id, u.id AS user_id FROM patients p JOIN users u ON p.user_id = u.id WHERE p.id = :pid"),
        {"pid": pid},
    )
    patient_row = check.mappings().first()
    if not patient_row:
        raise HTTPException(404, f"Patient {patient_id} not found")

    allowed = {
        "full_name", "email", "phone", "blood_group", "abha_id", "address",
        "emergency_contact_name", "emergency_contact_phone", "gender",
    }
    updates = {k: v for k, v in body.items() if k in allowed and v is not None}
    if not updates:
        raise HTTPException(400, "No valid fields to update")

    # Split user vs patient fields
    user_fields = {"phone", "email", "full_name"}
    patient_fields = allowed - user_fields
    rows_affected = 0

    if any(k in user_fields for k in updates):
        user_sets = ", ".join(f"{k} = :{k}" for k in updates if k in user_fields)
        if user_sets:
            result = await db.execute(
                text(f"UPDATE users SET {user_sets} WHERE id = :uid"),
                {**{k: updates[k] for k in updates if k in user_fields}, "uid": patient_row["user_id"]},
            )
            rows_affected += result.rowcount
    if any(k in patient_fields for k in updates):
        patient_sets = ", ".join(f"{k} = :{k}" for k in updates if k in patient_fields)
        if patient_sets:
            result = await db.execute(
                text(f"UPDATE patients SET {patient_sets}, updated_at = NOW() WHERE id = :pid"),
                {**{k: updates[k] for k in updates if k in patient_fields}, "pid": pid},
            )
            rows_affected += result.rowcount

    if rows_affected == 0:
        raise HTTPException(500, "Update failed — no rows were modified")

    await db.commit()

    # ── Return the actual updated data so callers see real values ──
    updated = await db.execute(
        text("""
            SELECT u.full_name, u.email, u.phone, p.gender, p.blood_group,
                   p.abha_id, p.address, p.emergency_contact_name, p.emergency_contact_phone
            FROM patients p JOIN users u ON p.user_id = u.id WHERE p.id = :pid
        """),
        {"pid": pid},
    )
    row = updated.mappings().first()
    updated_data = {k: str(v) if v is not None else None for k, v in row.items()} if row else {}

    return {
        "message": "Patient updated successfully",
        "patient_id": patient_id,
        "updated_fields": list(updates.keys()),
        "current_data": updated_data,
    }


# ═══════════════════════════════════════════════════════════
# SESSION OVERVIEW
# ═══════════════════════════════════════════════════════════

@router.get("/sessions")
async def list_all_sessions(
    date_str: Optional[str] = Query(None, description="Filter by date (YYYY-MM-DD)"),
    status: Optional[str] = Query(None, description="Filter by status"),
    specialization: Optional[str] = Query(None, description="Filter by department"),
    doctor_id: Optional[str] = Query(None, description="Filter by doctor"),
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """All sessions across all doctors."""
    import logging
    logger = logging.getLogger(__name__)

    try:
        conditions = []
        params = {}

        if date_str:
            conditions.append("s.session_date = :filter_date")
            params["filter_date"] = date.fromisoformat(date_str)
        if status:
            conditions.append("s.status = :sess_status")
            params["sess_status"] = status
        if specialization:
            conditions.append("d.specialization = :spec")
            params["spec"] = specialization
        if doctor_id:
            conditions.append("d.id = :doc_id")
            params["doc_id"] = UUID(doctor_id)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        query = f"""
            SELECT s.id, s.session_date, s.start_time, s.end_time,
                   s.slot_duration_minutes, s.max_patients_per_slot, s.total_slots,
                   s.booked_count, s.delay_minutes, s.status, s.notes, s.created_at,
                   d.id AS doctor_id, d.specialization,
                   u.full_name AS doctor_name,
                   (SELECT COUNT(*) FROM appointments a
                    WHERE a.session_id = s.id AND a.status != 'cancelled') AS active_appointments
            FROM sessions s
            JOIN doctors d ON s.doctor_id = d.id
            JOIN users u ON d.user_id = u.id
            {where}
            ORDER BY s.session_date DESC, s.start_time, u.full_name
            LIMIT 200
        """

        result = await db.execute(text(query), params)
        rows = result.mappings().all()

        out = []
        for r in rows:
            d = {}
            for k, v in r.items():
                d[k] = str(v) if v is not None else None
            out.append(d)
        return out
    except Exception as e:
        logger.exception("Admin sessions endpoint failed")
        raise HTTPException(500, detail=f"Sessions query failed: {str(e)}")


# ─── POST /admin/quick-register — staff quick-register a walk-in patient ────

@router.post("/quick-register")
async def quick_register_patient(
    body: dict,
    user: User = Depends(require_role("nurse", "admin", "doctor")),
    db: AsyncSession = Depends(get_db),
):
    """Quick-register a new patient with minimal info (name only). Returns patient_id."""
    import uuid as _uuid
    from datetime import date as _date_type
    from go.models.patient_relationship import RelationshipModel

    full_name = (body.get("full_name") or "").strip()
    if not full_name or len(full_name) < 2:
        raise HTTPException(400, "Full name is required (min 2 chars)")

    phone = (body.get("phone") or "").strip() or None
    placeholder_email = f"walkin_{_uuid.uuid4().hex[:8]}@dpms.local"

    # 1. Create user
    new_user = await UserModel.create(
        db,
        email=placeholder_email,
        full_name=full_name,
        role="patient",
        password_hash="WALKIN_NO_LOGIN",
        phone=phone,
    )

    # 2. Create patient record
    new_patient = await PatientModel.create(
        db,
        user_id=new_user.id,
        date_of_birth=_date_type(2000, 1, 1),
        gender="other",
    )

    # 3. Self-relationship
    try:
        await RelationshipModel.create(
            db,
            booker_patient_id=new_patient.id,
            beneficiary_patient_id=new_patient.id,
            relationship_type="self",
        )
    except Exception:
        pass

    await db.commit()

    return {
        "status": "registered",
        "message": f"{full_name} registered successfully.",
        "patient_id": str(new_patient.id),
    }
