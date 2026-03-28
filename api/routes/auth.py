"""
Auth Routes — 5 endpoints for authentication.

POST /register  → Create new patient account
POST /login     → Email/password login, returns JWT tokens
POST /google    → Google OAuth login (placeholder for now)
POST /refresh   → Exchange refresh token for new access token
GET  /me        → Get current user profile

Each route is THIN — it receives the request, calls the service, returns the response.
No business logic here.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, get_current_patient
from go.models.user import User
from go.models.patient import Patient, PatientModel
from go.services.user_service import register_patient, login, refresh_access_token
from api.schemas.auth_schemas import (
    RegisterRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserResponse,
    PatientResponse,
    MeResponse,
)

# Create a router — this gets mounted on /api/auth in main.py
router = APIRouter()


# ─── POST /register ──────────────────────────────────────────
@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new patient",
    description="Creates user + patient + self-relationship. Returns JWT tokens.",
)
async def register_route(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """
    Streamlit registration form calls this endpoint.
    On success, the user is immediately logged in (tokens returned).
    """
    try:
        result = await register_patient(
            db=db,
            email=body.email,
            password=body.password,
            full_name=body.full_name,
            date_of_birth=body.date_of_birth,
            gender=body.gender,
            phone=body.phone,
            abha_id=body.abha_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


# ─── POST /login ─────────────────────────────────────────────
@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login with email and password",
    description=(
        "Email/password login. Returns JWT tokens.\n\n"
        "Test with seed data: POST /api/auth/login "
        '{"email": "ravi.kumar@gmail.com", "password": "password123"}\n\n'
        "All seed users have password: password123"
    ),
)
async def login_route(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """
    Accepts OAuth2 form data (username + password).
    The 'username' field is the user's email address.
    Swagger Authorize button and Streamlit both use this.
    """
    try:
        result = await login(db=db, email=form_data.username, password=form_data.password)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )


# ─── POST /google ────────────────────────────────────────────
@router.post(
    "/google",
    summary="Google OAuth login (not implemented)",
    description="Placeholder for Google OAuth. Returns 501 for local development.",
)
async def google_login_route():
    """
    Google OAuth is not needed for local development.
    We use email/password login via Streamlit forms instead.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Google OAuth not implemented for local development. Use email/password login.",
    )


# ─── POST /refresh ───────────────────────────────────────────
@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
    description="Send your refresh_token to get a new access_token without re-logging in.",
)
async def refresh_route(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """
    When the access token expires (15 min), the frontend calls this
    with the refresh token to get a new access token silently.
    """
    try:
        result = await refresh_access_token(db=db, refresh_token=body.refresh_token)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )


# ─── GET /me ─────────────────────────────────────────────────
@router.get(
    "/me",
    response_model=MeResponse,
    summary="Get current user profile",
    description="Returns the authenticated user's profile. If patient, includes patient details.",
)
async def me_route(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    The frontend calls this on page load to check if the user is logged in
    and to get their profile info (name, role, patient details).

    Requires: Authorization: Bearer <access_token> header.
    """
    # Build user response
    user_data = UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        phone=user.phone,
        is_active=user.is_active,
    )

    # If user is a patient, load their patient profile too
    patient_data = None
    if user.role == "patient":
        patient = await PatientModel.get_by_user_id(db, user.id)
        if patient:
            patient_data = PatientResponse(
                id=str(patient.id),
                abha_id=patient.abha_id,
                date_of_birth=patient.date_of_birth,
                gender=patient.gender,
                blood_group=patient.blood_group,
                risk_score=float(patient.risk_score),
            )

    return MeResponse(user=user_data, patient=patient_data)
