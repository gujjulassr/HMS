"""
Patient Routes — profile management and family relationships.

All endpoints require patient role (enforced by get_current_patient dependency).
Mounted at: /api/patients
"""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text as sql_text

from database import get_db
from dependencies import get_current_user, get_current_patient, require_role
from go.models.user import User, UserModel
from go.models.patient import Patient, PatientModel
from go.models.patient_relationship import PatientRelationship, RelationshipModel
from api.schemas.patient_schemas import (
    UpdatePatientRequest,
    AddRelationshipRequest,
    UpdateFamilyMemberRequest,
    PatientProfileResponse,
    RelationshipResponse,
)

router = APIRouter()


# ─── Helpers ──────────────────────────────────────────────────

def _calculate_age(dob: date) -> int:
    """Calculate age from date of birth."""
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _build_profile_response(user: User, patient: Patient) -> PatientProfileResponse:
    """Combine user + patient data into a single response."""
    return PatientProfileResponse(
        patient_id=str(patient.id),
        user_id=str(user.id),
        full_name=user.full_name,
        email=user.email,
        date_of_birth=patient.date_of_birth,
        age=_calculate_age(patient.date_of_birth),
        gender=patient.gender,
        phone=user.phone,
        abha_id=patient.abha_id,
        blood_group=patient.blood_group,
        emergency_contact_name=patient.emergency_contact_name,
        emergency_contact_phone=patient.emergency_contact_phone,
        address=patient.address,
        risk_score=float(patient.risk_score),
        is_active=user.is_active,
        created_at=patient.created_at,
    )


def _build_relationship_response(
    rel: PatientRelationship,
    ben_user: User | None = None,
    ben_patient: Patient | None = None,
) -> RelationshipResponse:
    resp = RelationshipResponse(
        relationship_id=str(rel.id),
        booker_patient_id=str(rel.booker_patient_id),
        beneficiary_patient_id=str(rel.beneficiary_patient_id),
        relationship_type=rel.relationship_type,
        beneficiary_name=ben_user.full_name if ben_user else None,
        is_approved=rel.is_approved,
        created_at=rel.created_at,
    )
    if ben_user:
        resp.beneficiary_email = ben_user.email
        resp.beneficiary_phone = ben_user.phone
    if ben_patient:
        resp.beneficiary_gender = ben_patient.gender
        resp.beneficiary_date_of_birth = ben_patient.date_of_birth
        resp.beneficiary_age = _calculate_age(ben_patient.date_of_birth)
        resp.beneficiary_blood_group = ben_patient.blood_group
        resp.beneficiary_abha_id = ben_patient.abha_id
        resp.beneficiary_address = ben_patient.address
        resp.beneficiary_emergency_contact_name = ben_patient.emergency_contact_name
        resp.beneficiary_emergency_contact_phone = ben_patient.emergency_contact_phone
    return resp


# ─── GET /me — my patient profile ────────────────────────────

@router.get("/me", response_model=PatientProfileResponse)
async def get_my_profile(
    user: User = Depends(get_current_user),
    patient: Patient = Depends(get_current_patient),
):
    """Return the authenticated patient's full profile."""
    return _build_profile_response(user, patient)


# ─── PUT /me — update my profile ─────────────────────────────

@router.put("/me", response_model=PatientProfileResponse)
async def update_my_profile(
    body: UpdatePatientRequest,
    user: User = Depends(get_current_user),
    patient: Patient = Depends(get_current_patient),
    db: AsyncSession = Depends(get_db),
):
    """Update editable fields on the patient's profile."""
    patient_updates = {}
    user_updates = {}

    # Only include fields that actually changed (skip unchanged values)
    if body.phone is not None:
        val = body.phone.strip() or None
        if val != user.phone:
            user_updates["phone"] = val
    if body.abha_id is not None:
        val = body.abha_id.strip() or None
        if val != patient.abha_id:
            patient_updates["abha_id"] = val
    if body.blood_group is not None:
        if body.blood_group != patient.blood_group:
            patient_updates["blood_group"] = body.blood_group
    if body.emergency_contact_name is not None:
        val = body.emergency_contact_name.strip() or None
        if val != patient.emergency_contact_name:
            patient_updates["emergency_contact_name"] = val
    if body.emergency_contact_phone is not None:
        val = body.emergency_contact_phone.strip() or None
        if val != patient.emergency_contact_phone:
            patient_updates["emergency_contact_phone"] = val
    if body.address is not None:
        val = body.address.strip() or None
        if val != patient.address:
            patient_updates["address"] = val

    try:
        if user_updates:
            user = await UserModel.update(db, user.id, **user_updates)
        if patient_updates:
            patient = await PatientModel.update(db, patient.id, **patient_updates)
        await db.commit()
    except Exception as e:
        await db.rollback()
        msg = str(e).lower()
        if "unique" in msg:
            if "abha_id" in msg:
                raise HTTPException(400, "This ABHA ID / UHID is already in use by another patient.")
            if "phone" in msg:
                raise HTTPException(400, "This phone number is already in use by another account.")
            if "email" in msg:
                raise HTTPException(400, "This email is already in use by another account.")
            raise HTTPException(400, "A value you entered is already in use by another account.")
        raise HTTPException(500, f"Profile update failed: {e}")

    return _build_profile_response(user, patient)


# ─── GET /me/relationships — my family members ───────────────

@router.get("/me/relationships", response_model=list[RelationshipResponse])
async def get_my_relationships(
    patient: Patient = Depends(get_current_patient),
    db: AsyncSession = Depends(get_db),
):
    """List all people this patient can book for (including self)."""
    relationships = await RelationshipModel.get_beneficiaries(db, patient.id)

    results = []
    for rel in relationships:
        ben_patient = await PatientModel.get_by_id(db, rel.beneficiary_patient_id)
        ben_user = None
        if ben_patient:
            ben_user = await UserModel.get_by_id(db, ben_patient.user_id)
        results.append(_build_relationship_response(rel, ben_user, ben_patient))

    return results


# ─── POST /me/relationships — add a family member ────────────

@router.post(
    "/me/relationships",
    response_model=RelationshipResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_relationship(
    body: AddRelationshipRequest,
    patient: Patient = Depends(get_current_patient),
    db: AsyncSession = Depends(get_db),
):
    """Link another patient as a family member you can book for."""
    beneficiary_id = UUID(body.beneficiary_patient_id)

    # Can't link yourself (self-relationship created at registration)
    if beneficiary_id == patient.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Self-relationship already exists from registration",
        )

    # Check beneficiary exists
    beneficiary = await PatientModel.get_by_id(db, beneficiary_id)
    if not beneficiary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Beneficiary patient not found",
        )

    # Check not already linked (pending or approved)
    already_linked = await RelationshipModel.check_exists(db, patient.id, beneficiary_id)
    if already_linked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Relationship already exists (pending or approved)",
        )

    # Create the relationship (pending approval)
    rel = await RelationshipModel.create(
        db,
        booker_patient_id=patient.id,
        beneficiary_patient_id=beneficiary_id,
        relationship_type=body.relationship_type,
    )
    await db.commit()

    # Get beneficiary details for response
    ben_user = await UserModel.get_by_id(db, beneficiary.user_id)

    return _build_relationship_response(rel, ben_user, beneficiary)


# ─── GET /me/find-beneficiary — patient searches by ABHA/UHID to link family ──

@router.get("/me/find-beneficiary")
async def find_beneficiary(
    abha_id: str = Query(..., min_length=2, description="Search by ABHA ID or UHID"),
    patient: Patient = Depends(get_current_patient),
    db: AsyncSession = Depends(get_db),
):
    """
    Patient-facing: find another patient by ABHA/UHID to add as family member.
    Returns limited info (name, age, gender) — no sensitive fields exposed.
    """
    result = await db.execute(
        sql_text("""
            SELECT u.full_name, p.id as patient_id, p.date_of_birth, p.gender,
                   p.abha_id
            FROM patients p
            JOIN users u ON u.id = p.user_id
            WHERE p.abha_id = :abha
              AND p.id != :self_id
            LIMIT 5
        """),
        {"abha": abha_id.strip(), "self_id": patient.id},
    )
    rows = result.mappings().all()
    matches = []
    for row in rows:
        age = None
        if row["date_of_birth"]:
            today = date.today()
            dob = row["date_of_birth"]
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        matches.append({
            "patient_id": str(row["patient_id"]),
            "full_name": row["full_name"],
            "age": age,
            "gender": row["gender"],
            "abha_id": row["abha_id"],
        })
    return matches


# ─── POST /me/add-family — register a new family member + link relationship ──

@router.post("/me/add-family", status_code=status.HTTP_201_CREATED)
async def add_family_member(
    body: dict,
    user: User = Depends(get_current_user),
    patient: Patient = Depends(get_current_patient),
    db: AsyncSession = Depends(get_db),
):
    """
    Patient-facing: register a new family member who isn't in the system yet,
    and link them as a beneficiary in one step.
    Creates: user → patient → self-relationship → booker-relationship.
    """
    import uuid as _uuid

    # Gate: booker must have their own UHID/ABHA set before linking family
    if not patient.abha_id:
        raise HTTPException(
            400,
            "You must set your own UHID (ABHA ID) in your profile before adding family members.",
        )

    full_name = (body.get("full_name") or "").strip()
    if not full_name or len(full_name) < 2:
        raise HTTPException(400, "Full name is required (min 2 chars)")

    relationship_type = body.get("relationship_type", "other")
    if relationship_type not in ("spouse", "parent", "child", "sibling", "guardian", "other"):
        raise HTTPException(400, "Invalid relationship type")

    # Parse optional fields
    phone = (body.get("phone") or "").strip() or None
    gender = body.get("gender") or "other"
    dob_str = body.get("date_of_birth") or ""
    try:
        dob = date.fromisoformat(dob_str) if dob_str else date(2000, 1, 1)
    except Exception:
        dob = date(2000, 1, 1)

    blood_group = (body.get("blood_group") or "").strip() or None

    # Placeholder email — family member won't login
    placeholder_email = f"family_{_uuid.uuid4().hex[:8]}@dpms.local"

    # 1. Create user record
    new_user = await UserModel.create(
        db, email=placeholder_email, full_name=full_name,
        role="patient", password_hash="FAMILY_NO_LOGIN", phone=phone,
    )

    # 2. Create patient record
    new_patient = await PatientModel.create(
        db, user_id=new_user.id, date_of_birth=dob,
        gender=gender, blood_group=blood_group,
    )

    # 3. Self-relationship for the new patient
    try:
        await RelationshipModel.create(
            db, booker_patient_id=new_patient.id,
            beneficiary_patient_id=new_patient.id,
            relationship_type="self",
        )
    except Exception:
        pass  # non-critical

    # 4. Link booker → new family member (auto-approved)
    rel = await RelationshipModel.create(
        db, booker_patient_id=patient.id,
        beneficiary_patient_id=new_patient.id,
        relationship_type=relationship_type,
    )
    # Auto-approve since the booker is creating the record
    await db.execute(
        sql_text("UPDATE patient_relationships SET is_approved = true, approved_at = NOW() WHERE id = :id"),
        {"id": rel.id},
    )
    await db.commit()

    return {
        "status": "created",
        "message": f"{full_name} added as {relationship_type} and linked to your account.",
        "patient_id": str(new_patient.id),
        "beneficiary_name": full_name,
        "relationship_type": relationship_type,
    }


# ─── PUT /me/relationships/{id}/beneficiary — edit family member details ───

@router.put(
    "/me/relationships/{relationship_id}/beneficiary",
    response_model=RelationshipResponse,
)
async def update_family_member_details(
    relationship_id: str,
    body: UpdateFamilyMemberRequest,
    patient: Patient = Depends(get_current_patient),
    db: AsyncSession = Depends(get_db),
):
    """Update a family member's profile details (name, phone, blood group, etc)."""
    rel_id = UUID(relationship_id)

    # Verify this relationship belongs to the current patient
    result = await db.execute(
        sql_text(
            "SELECT * FROM patient_relationships WHERE id = :id AND booker_patient_id = :pid"
        ),
        {"id": rel_id, "pid": patient.id},
    )
    rel_row = result.mappings().first()
    if not rel_row:
        raise HTTPException(404, "Relationship not found or you don't have access.")

    ben_patient_id = rel_row["beneficiary_patient_id"]
    ben_patient = await PatientModel.get_by_id(db, ben_patient_id)
    if not ben_patient:
        raise HTTPException(404, "Beneficiary patient record not found.")
    ben_user = await UserModel.get_by_id(db, ben_patient.user_id)
    if not ben_user:
        raise HTTPException(404, "Beneficiary user record not found.")

    # Build updates for patient and user tables
    patient_updates = {}
    user_updates = {}

    if body.full_name is not None and body.full_name != ben_user.full_name:
        user_updates["full_name"] = body.full_name.strip()
    if body.phone is not None:
        val = body.phone.strip() or None
        if val != ben_user.phone:
            user_updates["phone"] = val
    if body.gender is not None and body.gender != ben_patient.gender:
        patient_updates["gender"] = body.gender
    if body.date_of_birth is not None and body.date_of_birth != ben_patient.date_of_birth:
        patient_updates["date_of_birth"] = body.date_of_birth
    if body.blood_group is not None and body.blood_group != ben_patient.blood_group:
        patient_updates["blood_group"] = body.blood_group
    if body.address is not None:
        val = body.address.strip() or None
        if val != ben_patient.address:
            patient_updates["address"] = val
    if body.emergency_contact_name is not None:
        val = body.emergency_contact_name.strip() or None
        if val != ben_patient.emergency_contact_name:
            patient_updates["emergency_contact_name"] = val
    if body.emergency_contact_phone is not None:
        val = body.emergency_contact_phone.strip() or None
        if val != ben_patient.emergency_contact_phone:
            patient_updates["emergency_contact_phone"] = val

    # Update relationship type if changed
    if body.relationship_type is not None and body.relationship_type != rel_row["relationship_type"]:
        await db.execute(
            sql_text("UPDATE patient_relationships SET relationship_type = :rt WHERE id = :id"),
            {"rt": body.relationship_type, "id": rel_id},
        )

    try:
        if user_updates:
            ben_user = await UserModel.update(db, ben_user.id, **user_updates)
        if patient_updates:
            ben_patient = await PatientModel.update(db, ben_patient.id, **patient_updates)
        await db.commit()
    except Exception as e:
        await db.rollback()
        msg = str(e).lower()
        if "unique" in msg:
            raise HTTPException(400, "A value you entered conflicts with an existing record.")
        raise HTTPException(500, f"Update failed: {e}")

    # Re-fetch relationship to get updated data
    result2 = await db.execute(
        sql_text("SELECT * FROM patient_relationships WHERE id = :id"),
        {"id": rel_id},
    )
    updated_rel_row = result2.mappings().first()
    rel_obj = PatientRelationship(**dict(updated_rel_row))

    return _build_relationship_response(rel_obj, ben_user, ben_patient)


# ─── GET /search — staff search patients by name/phone ───────

@router.get("/search")
async def search_patients(
    q: str = Query(..., min_length=2, description="Search by name or phone"),
    user: User = Depends(require_role("nurse", "doctor", "admin")),
    db: AsyncSession = Depends(get_db),
):
    """Staff-only: search patients by name or phone number."""
    search_term = f"%{q}%"
    result = await db.execute(
        sql_text("""
            SELECT u.full_name, u.email, u.phone,
                   p.id as patient_id, p.date_of_birth, p.gender,
                   p.blood_group, p.abha_id, p.address,
                   p.emergency_contact_name, p.emergency_contact_phone,
                   p.risk_score
            FROM patients p
            JOIN users u ON u.id = p.user_id
            WHERE u.full_name ILIKE :q OR u.phone ILIKE :q OR u.email ILIKE :q
            ORDER BY u.full_name
            LIMIT 20
        """),
        {"q": search_term},
    )
    rows = result.mappings().all()
    patients = []
    for row in rows:
        age = None
        if row["date_of_birth"]:
            today = date.today()
            dob = row["date_of_birth"]
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        patients.append({
            "patient_id": str(row["patient_id"]),
            "full_name": row["full_name"],
            "email": row["email"],
            "phone": row["phone"],
            "age": age,
            "gender": row["gender"],
            "blood_group": row["blood_group"],
            "abha_id": row["abha_id"],
            "address": row["address"],
            "emergency_contact_name": row["emergency_contact_name"],
            "emergency_contact_phone": row["emergency_contact_phone"],
            "risk_score": float(row["risk_score"]) if row["risk_score"] is not None else 0,
        })
    return patients
