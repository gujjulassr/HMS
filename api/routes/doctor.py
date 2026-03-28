"""
Doctor Routes — browse doctors and their available sessions.

Used by patients to find a doctor and pick a session for booking.
Any authenticated user can access these (no role restriction).
Mounted at: /api/doctors
"""
from datetime import date
from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user
from go.models.user import User, UserModel
from go.models.doctor import Doctor, DoctorModel
from go.models.session import Session, SessionModel
from api.schemas.doctor_schemas import (
    DoctorListItem,
    DoctorDetailResponse,
    SessionResponse,
)

router = APIRouter()


# ─── Helpers ──────────────────────────────────────────────────

def _build_list_item(doctor: Doctor, user: User) -> DoctorListItem:
    return DoctorListItem(
        doctor_id=str(doctor.id),
        user_id=str(user.id),
        full_name=user.full_name,
        specialization=doctor.specialization,
        qualification=doctor.qualification,
        consultation_fee=float(doctor.consultation_fee),
        is_available=doctor.is_available,
    )


def _build_detail_response(doctor: Doctor, user: User) -> DoctorDetailResponse:
    return DoctorDetailResponse(
        doctor_id=str(doctor.id),
        user_id=str(user.id),
        full_name=user.full_name,
        email=user.email,
        phone=user.phone,
        specialization=doctor.specialization,
        qualification=doctor.qualification,
        license_number=doctor.license_number,
        consultation_fee=float(doctor.consultation_fee),
        max_patients_per_slot=doctor.max_patients_per_slot,
        is_available=doctor.is_available,
        created_at=doctor.created_at,
    )


def _build_session_response(session: Session) -> SessionResponse:
    capacity = (session.total_slots * session.max_patients_per_slot) - session.booked_count
    return SessionResponse(
        session_id=str(session.id),
        doctor_id=str(session.doctor_id),
        session_date=session.session_date,
        start_time=session.start_time,
        end_time=session.end_time,
        slot_duration_minutes=session.slot_duration_minutes,
        max_patients_per_slot=session.max_patients_per_slot,
        total_slots=session.total_slots,
        booked_count=session.booked_count,
        available_capacity=max(capacity, 0),
        delay_minutes=session.delay_minutes,
        status=session.status,
    )


# ─── GET / — list all doctors ────────────────────────────────

@router.get("/", response_model=list[DoctorListItem])
async def list_doctors(
    specialization: Optional[str] = Query(None, description="Filter by specialization (partial match)"),
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Browse available doctors. Patients use this to find who to book with.
    Optional filter by specialization (e.g. 'cardio' matches 'Cardiology').
    """
    doctors = await DoctorModel.list_by_specialization(
        db, specialization=specialization, only_available=True
    )

    results = []
    for doc in doctors:
        user = await UserModel.get_by_id(db, doc.user_id)
        if user:
            results.append(_build_list_item(doc, user))
    return results


# ─── GET /{doctor_id} — one doctor's full details ────────────

@router.get("/{doctor_id}", response_model=DoctorDetailResponse)
async def get_doctor(
    doctor_id: str,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get full details for a specific doctor."""
    doctor = await DoctorModel.get_by_id(db, UUID(doctor_id))
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor not found",
        )

    user = await UserModel.get_by_id(db, doctor.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor user profile not found",
        )

    return _build_detail_response(doctor, user)


# ─── GET /{doctor_id}/sessions — upcoming sessions ───────────

@router.get("/{doctor_id}/sessions", response_model=list[SessionResponse])
async def get_doctor_sessions(
    doctor_id: str,
    date_from: Optional[date] = Query(None, description="Start date filter (YYYY-MM-DD)"),
    date_to: Optional[date] = Query(None, description="End date filter (YYYY-MM-DD)"),
    include_all: bool = Query(False, description="True = return ALL sessions (any status). False = active with capacity only."),
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List a doctor's sessions.
    - Default (include_all=false): active sessions with remaining capacity (for patient booking).
    - include_all=true: ALL sessions any status (for doctor dashboard).
    """
    doctor = await DoctorModel.get_by_id(db, UUID(doctor_id))
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor not found",
        )

    if include_all:
        sessions = await SessionModel.get_all_sessions(
            db, doctor_id=UUID(doctor_id), date_from=date_from, date_to=date_to,
        )
    else:
        sessions = await SessionModel.get_available_sessions(
            db, doctor_id=UUID(doctor_id), date_from=date_from, date_to=date_to,
        )

    return [_build_session_response(s) for s in sessions]


# ─── GET /{doctor_id}/all-sessions — all sessions any status ──

@router.get("/{doctor_id}/all-sessions", response_model=list[SessionResponse])
async def get_all_doctor_sessions(
    doctor_id: str,
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """All sessions for a doctor (active, completed, cancelled) — for doctor dashboard."""
    doctor = await DoctorModel.get_by_id(db, UUID(doctor_id))
    if not doctor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Doctor not found")

    sessions = await SessionModel.get_all_sessions(
        db, doctor_id=UUID(doctor_id), date_from=date_from, date_to=date_to,
    )
    return [_build_session_response(s) for s in sessions]
