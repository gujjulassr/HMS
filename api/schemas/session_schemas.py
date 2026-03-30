"""
Session Management Schemas — for staff/doctor real-time actions.

Doctor check-in, live delay updates, overtime window,
extend session, cancel session, affected patient options.
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import time, datetime


# ─── Request Schemas (what comes IN) ────────────────────────

class DoctorCheckinRequest(BaseModel):
    """Staff marks doctor as arrived. Delay auto-calculated."""
    session_id: str


class UpdateDelayRequest(BaseModel):
    """Staff updates live delay during the session."""
    session_id: str
    delay_minutes: int = Field(ge=0, description="Current delay in minutes")
    reason: Optional[str] = Field(None, description="Why the delay changed")


class OvertimeWindowRequest(BaseModel):
    """
    Staff sets overtime window when session is running late.
    System calculates who can be seen in overtime vs who can't.
    Patients who can't be seen get notified with options.
    """
    session_id: str
    overtime_minutes: int = Field(
        ge=0, le=60,
        description="How many extra minutes doctor is willing to stay (0 = no overtime)"
    )


class ExtendSessionRequest(BaseModel):
    """Doctor decides to stay late to see remaining patients."""
    session_id: str
    new_end_time: time = Field(description="Extended end time (e.g. 13:30)")
    note: Optional[str] = Field(None, description="Reason for overtime")


class CompleteSessionRequest(BaseModel):
    """Doctor marks session as done for the day."""
    session_id: str
    note: Optional[str] = Field(None, description="Optional closing note")


class CreateSessionRequest(BaseModel):
    """Create a new session for a doctor."""
    doctor_id: Optional[str] = Field(None, description="Doctor UUID. Omit for self (doctor role).")
    session_date: str = Field(description="Date YYYY-MM-DD")
    start_time: str = Field(description="Start time HH:MM (24h)")
    end_time: str = Field(description="End time HH:MM (24h)")
    slot_duration_minutes: int = Field(15, ge=5, le=60, description="Minutes per slot")
    max_patients_per_slot: int = Field(2, ge=1, le=10, description="Max patients per slot")


class CancelSessionRequest(BaseModel):
    """Cancel entire session — all appointments affected."""
    session_id: str
    reason: str = Field(min_length=5, description="Why the session is being cancelled")


# ─── Response Schemas (what goes OUT) ────────────────────────

class SessionStatusResponse(BaseModel):
    """Real-time session status after staff action."""
    session_id: str
    status: str
    delay_minutes: int
    doctor_checkin_at: Optional[datetime] = None
    actual_end_time: Optional[time] = None
    notes: Optional[str] = None
    message: str


class AffectedPatient(BaseModel):
    """A patient affected by delay/overtime decisions."""
    appointment_id: str
    patient_id: str
    patient_name: Optional[str] = None
    slot_number: int
    original_time: Optional[time] = None
    estimated_new_time: Optional[time] = None
    can_be_seen: bool
    notification_sent: bool = False


class OvertimeWindowResponse(BaseModel):
    """Result of setting overtime window — shows who can/can't be seen."""
    session_id: str
    overtime_minutes: int
    session_end_time: time
    overtime_end_time: time
    patients_can_be_seen: list[AffectedPatient]
    patients_cannot_be_seen: list[AffectedPatient]
    message: str


class CancelSessionResponse(BaseModel):
    """Result of cancelling an entire session."""
    status: str
    message: str
    appointments_cancelled: int
    no_show_count: int = 0
    waitlist_cancelled: int
