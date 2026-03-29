"""
Patient Schemas — Pydantic models for patient profile & relationship endpoints.

Requests: validate updates and new relationships.
Responses: format patient profile and family data sent back to client.
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import date, datetime


# ─── Request Schemas (what comes IN) ────────────────────────

class UpdatePatientRequest(BaseModel):
    """Fields a patient can update on their own profile."""
    phone: Optional[str] = Field(None, description="Contact phone number")
    abha_id: Optional[str] = Field(None, max_length=14, description="14-digit UHID")
    blood_group: Optional[str] = Field(None, pattern="^(A|B|AB|O)[+-]$")
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    address: Optional[str] = None

    @field_validator("*", mode="before")
    @classmethod
    def empty_str_to_none(cls, v):
        """Treat empty or whitespace-only strings as None so validators don't trip."""
        if isinstance(v, str) and not v.strip():
            return None
        return v


class AddRelationshipRequest(BaseModel):
    """Link a family member you can book appointments for."""
    beneficiary_patient_id: str = Field(description="Patient ID of the person you're linking")
    relationship_type: str = Field(
        pattern="^(spouse|parent|child|sibling|guardian|other)$",
        description="How this person is related to you",
    )


class UpdateFamilyMemberRequest(BaseModel):
    """Fields that a booker can update on their family member's profile."""
    full_name: Optional[str] = None
    phone: Optional[str] = None
    gender: Optional[str] = Field(None, pattern="^(male|female|other)$")
    date_of_birth: Optional[date] = None
    blood_group: Optional[str] = Field(None, pattern="^(A|B|AB|O)[+-]$")
    address: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    relationship_type: Optional[str] = Field(
        None, pattern="^(spouse|parent|child|sibling|guardian|other)$"
    )

    @field_validator("*", mode="before")
    @classmethod
    def empty_str_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v


# ─── Response Schemas (what goes OUT) ────────────────────────

class PatientProfileResponse(BaseModel):
    """Full patient profile — returned by GET /me and PUT /me."""
    patient_id: str
    user_id: str
    full_name: str
    email: str
    date_of_birth: date
    age: int
    gender: str
    phone: Optional[str] = None
    abha_id: Optional[str] = None
    blood_group: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    address: Optional[str] = None
    risk_score: float
    is_active: bool
    created_at: datetime


class RelationshipResponse(BaseModel):
    """One family relationship — returned in list and after creation."""
    relationship_id: str
    booker_patient_id: str
    beneficiary_patient_id: str
    relationship_type: str
    beneficiary_name: Optional[str] = None
    is_approved: bool
    created_at: datetime
    # Full beneficiary details
    beneficiary_email: Optional[str] = None
    beneficiary_phone: Optional[str] = None
    beneficiary_gender: Optional[str] = None
    beneficiary_date_of_birth: Optional[date] = None
    beneficiary_age: Optional[int] = None
    beneficiary_blood_group: Optional[str] = None
    beneficiary_abha_id: Optional[str] = None
    beneficiary_address: Optional[str] = None
    beneficiary_emergency_contact_name: Optional[str] = None
    beneficiary_emergency_contact_phone: Optional[str] = None
