"""
Auth Schemas — Pydantic models for request validation & response formatting.

Requests: validate what the user sends (email format, password length, etc.)
Responses: format what we send back (tokens, user profile, etc.)
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import date


# ─── Request Schemas (what comes IN) ────────────────────────

class RegisterRequest(BaseModel):
    """Patient registration form data from Streamlit."""
    email: EmailStr
    password: str = Field(min_length=8, description="Minimum 8 characters")
    full_name: str = Field(min_length=2)
    date_of_birth: date
    gender: str = Field(pattern="^(male|female|other)$")
    phone: Optional[str] = None
    abha_id: Optional[str] = Field(None, max_length=14, description="14-digit UHID (dummy for local)")


class LoginRequest(BaseModel):
    """Email + password login."""
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    """Exchange a refresh token for a new access token."""
    refresh_token: str


# ─── Response Schemas (what goes OUT) ────────────────────────

class TokenResponse(BaseModel):
    """Returned after login or register — contains JWT tokens."""
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    user_id: str
    patient_id: Optional[str] = None
    role: str


class UserResponse(BaseModel):
    """User profile info (safe to expose — no password hash)."""
    id: str
    email: str
    full_name: str
    role: str
    phone: Optional[str] = None
    is_active: bool


class PatientResponse(BaseModel):
    """Patient medical profile info."""
    id: str
    abha_id: Optional[str] = None
    date_of_birth: date
    gender: str
    blood_group: Optional[str] = None
    risk_score: float


class MeResponse(BaseModel):
    """Combined response for GET /me — user + patient profile if applicable."""
    user: UserResponse
    patient: Optional[PatientResponse] = None
