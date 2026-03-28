"""
Queue Schemas — Pydantic models for in-clinic queue management.

Nurse checks in patient → sets visual_priority → doctor calls next → marks complete.
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, time


# ─── Request Schemas (what comes IN) ────────────────────────

class PatientCheckinRequest(BaseModel):
    """Nurse checks in a patient who has arrived at the clinic."""
    appointment_id: str
    visual_priority: int = Field(
        default=5, ge=1, le=10,
        description="Nurse-set priority 1-10 (10 = most urgent). Affects queue order."
    )
    priority_tier: Optional[str] = Field(
        default="NORMAL",
        description="NORMAL, HIGH, or CRITICAL — nurse sets based on visual inspection."
    )
    is_emergency: Optional[bool] = Field(
        default=False,
        description="Nurse marks patient as emergency based on visual assessment."
    )
    duration_minutes: Optional[int] = Field(
        None, ge=5, le=120,
        description="Custom appointment duration in minutes. NULL = use session default."
    )


class SetDurationRequest(BaseModel):
    """Nurse sets a custom duration for any appointment."""
    appointment_id: str
    duration_minutes: int = Field(ge=5, le=120, description="Custom duration in minutes")


class CallNextRequest(BaseModel):
    """Doctor requests the next patient from the queue."""
    session_id: str


class CompleteAppointmentRequest(BaseModel):
    """Doctor marks current patient as done."""
    appointment_id: str
    notes: Optional[str] = Field(None, description="Doctor's notes about the visit")


class EscalatePriorityRequest(BaseModel):
    """Doctor / staff escalates a patient's priority or marks as emergency."""
    appointment_id: str
    priority_tier: Optional[str] = Field(None, description="NORMAL, HIGH, or CRITICAL")
    visual_priority: Optional[int] = Field(None, ge=1, le=10, description="1-10, 10 = most urgent")
    is_emergency: Optional[bool] = Field(None, description="Mark as emergency override")
    reason: str = Field(min_length=3, description="Reason for priority change")


class MarkNoShowRequest(BaseModel):
    """Staff marks unchecked patients as no-show after session ends."""
    session_id: str


class MarkSingleNoShowRequest(BaseModel):
    """Mark a single patient as no-show (booked or checked_in)."""
    appointment_id: str
    reason: Optional[str] = Field(None, description="Reason for no-show")


# ─── Response Schemas (what goes OUT) ────────────────────────

class QueueEntry(BaseModel):
    """One patient in the queue display."""
    appointment_id: str
    patient_id: str
    patient_name: Optional[str] = None
    patient_age: Optional[int] = None
    patient_gender: Optional[str] = None
    patient_blood_group: Optional[str] = None
    patient_phone: Optional[str] = None
    patient_address: Optional[str] = None
    patient_emergency_contact: Optional[str] = None
    patient_emergency_phone: Optional[str] = None
    patient_risk_score: Optional[float] = None
    patient_abha_id: Optional[str] = None
    slot_number: int
    slot_position: int
    priority_tier: str
    visual_priority: int
    is_emergency: bool
    status: str
    checked_in_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    queue_position: int  # computed: where they stand in line
    original_slot_time: Optional[time] = None       # scheduled time
    estimated_time: Optional[time] = None            # with delay factored in
    estimated_wait_minutes: Optional[int] = None     # how long from now
    duration_minutes: Optional[int] = None           # custom duration (NULL = default)


class QueueResponse(BaseModel):
    """Full queue for a session — what staff sees on the dashboard."""
    session_id: str
    doctor_name: Optional[str] = None
    session_date: Optional[str] = None
    session_status: Optional[str] = None
    session_start_time: Optional[str] = None
    session_end_time: Optional[str] = None
    delay_minutes: int = 0
    slot_duration_minutes: int = 15  # session default
    total_slots: int = 20
    booked_count: int = 0
    max_patients_per_slot: int = 2
    total_in_queue: int
    completed_count: int = 0
    current_patient: Optional[QueueEntry] = None
    queue: list[QueueEntry]


class CheckinResponse(BaseModel):
    """Returned after nurse checks in a patient."""
    status: str
    message: str
    queue_position: int
    appointment_id: str


class CompleteResponse(BaseModel):
    """Returned after doctor completes a patient."""
    status: str
    message: str
    next_patient: Optional[QueueEntry] = None


class NoShowResponse(BaseModel):
    """Returned after marking no-shows."""
    status: str
    message: str
    no_show_count: int
