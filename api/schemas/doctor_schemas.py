"""
Doctor Schemas — Pydantic models for doctor listing & session browsing.

These endpoints are read-only for patients (browsing doctors to book).
Doctors/admin will get separate write endpoints later.
"""
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, time, datetime


# ─── Response Schemas (what goes OUT) ────────────────────────

class DoctorListItem(BaseModel):
    """One doctor in the list — enough info for patient to pick."""
    doctor_id: str
    user_id: str
    full_name: str
    specialization: str
    qualification: str
    consultation_fee: float
    is_available: bool


class DoctorDetailResponse(BaseModel):
    """Full doctor profile — returned by GET /doctors/{id}."""
    doctor_id: str
    user_id: str
    full_name: str
    email: str
    phone: Optional[str] = None
    specialization: str
    qualification: str
    license_number: str
    consultation_fee: float
    max_patients_per_slot: int
    is_available: bool
    created_at: datetime


class SessionResponse(BaseModel):
    """One session slot — returned when browsing a doctor's availability."""
    session_id: str
    doctor_id: str
    session_date: date
    start_time: time
    end_time: time
    slot_duration_minutes: int
    max_patients_per_slot: int
    total_slots: int
    booked_count: int
    available_capacity: int
    delay_minutes: int
    status: str
