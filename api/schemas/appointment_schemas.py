"""
Appointment Schemas — Pydantic models for booking, cancellation, and listing.

Requests: validate booking/cancel input.
Responses: format appointment data with doctor/session info.
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import date, time, datetime


# ─── Request Schemas (what comes IN) ────────────────────────

class BookAppointmentRequest(BaseModel):
    """Book an appointment in a specific session slot."""
    session_id: str = Field(description="Which session to book in")
    slot_number: int = Field(ge=1, description="Which slot to book (1-based)")
    beneficiary_patient_id: str = Field(
        description="Patient ID of who the appointment is for (can be self or family)"
    )


class EmergencyBookRequest(BaseModel):
    """Staff-only: force-book an emergency patient into position 3."""
    session_id: str = Field(description="Which session")
    slot_number: int = Field(ge=1, description="Which slot")
    patient_id: str = Field(description="Patient who needs emergency slot")
    reason: str = Field(min_length=5, description="Why this is an emergency")


class CancelAppointmentRequest(BaseModel):
    """Cancel an existing appointment."""
    appointment_id: str
    reason: Optional[str] = Field(None, max_length=500, description="Why cancelling")


# ─── Response Schemas (what goes OUT) ────────────────────────

class AppointmentResponse(BaseModel):
    """Full appointment details — returned after booking, in lists, and by ID."""
    appointment_id: str
    session_id: str
    patient_id: str
    patient_name: Optional[str] = None
    booked_by_patient_id: str
    doctor_name: Optional[str] = None
    specialization: Optional[str] = None
    session_date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    slot_number: int
    slot_position: int
    priority_tier: str
    visual_priority: int
    is_emergency: bool
    status: str
    delay_minutes: Optional[int] = 0
    checked_in_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime


class AppointmentListResponse(BaseModel):
    """Paginated list of appointments."""
    appointments: list[AppointmentResponse]
    total: int


class BookingResultResponse(BaseModel):
    """Returned after a successful booking — appointment + waitlist info."""
    status: str  # "booked" or "waitlisted"
    message: str
    appointment: Optional[AppointmentResponse] = None
    waitlist_position: Optional[int] = None


class CancelResultResponse(BaseModel):
    """Returned after cancellation."""
    status: str
    message: str
    risk_delta: float
    new_risk_score: float
