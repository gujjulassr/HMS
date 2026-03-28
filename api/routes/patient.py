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
    rel: PatientRelationship, beneficiary_name: str | None = None
) -> RelationshipResponse:
    return RelationshipResponse(
        relationship_id=str(rel.id),
        booker_patient_id=str(rel.booker_patient_id),
        beneficiary_patient_id=str(rel.beneficiary_patient_id),
        relationship_type=rel.relationship_type,
        beneficiary_name=beneficiary_name,
        is_approved=rel.is_approved,
        created_at=rel.created_at,
    )


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
    # Collect only the fields that were actually sent (not None)
    patient_updates = {}
    user_updates = {}

    if body.phone is not None:
        user_updates["phone"] = body.phone
    if body.abha_id is not None:
        patient_updates["abha_id"] = body.abha_id
    if body.blood_group is not None:
        patient_updates["blood_group"] = body.blood_group
    if body.emergency_contact_name is not None:
        patient_updates["emergency_contact_name"] = body.emergency_contact_name
    if body.emergency_contact_phone is not None:
        patient_updates["emergency_contact_phone"] = body.emergency_contact_phone
    if body.address is not None:
        patient_updates["address"] = body.address

    # Apply updates
    if user_updates:
        user = await UserModel.update(db, user.id, **user_updates)
    if patient_updates:
        patient = await PatientModel.update(db, patient.id, **patient_updates)

    await db.commit()
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
        # Look up the beneficiary's name
        beneficiary = await PatientModel.get_by_id(db, rel.beneficiary_patient_id)
        if beneficiary:
            ben_user = await UserModel.get_by_id(db, beneficiary.user_id)
            name = ben_user.full_name if ben_user else None
        else:
            name = None
        results.append(_build_relationship_response(rel, name))

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

    # Get beneficiary name for response
    ben_user = await UserModel.get_by_id(db, beneficiary.user_id)
    name = ben_user.full_name if ben_user else None

    return _build_relationship_response(rel, name)


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
