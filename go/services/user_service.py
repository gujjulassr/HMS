"""
GO Service: User Authentication & Management

This is the BRAIN of auth. It handles:
- Password hashing (bcrypt)
- JWT token creation (access + refresh)
- Register (creates user + patient + self-relationship)
- Login (verify password, return tokens)
- Token refresh (exchange refresh token for new access token)

Pattern: Load GOs → Validate → Create/Update GOs → Return
"""
from uuid import UUID
from datetime import datetime, timedelta, date
from typing import Optional
from passlib.context import CryptContext
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from go.models.user import UserModel, User
from go.models.patient import PatientModel
from go.models.patient_relationship import RelationshipModel
from config import get_settings

settings = get_settings()


# ─── Password Hashing ────────────────────────────────────────
# CryptContext handles bcrypt hashing and verification
# "deprecated=auto" means old hash formats are still verifiable but new hashes use bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a plain text password. Used during registration."""
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Compare plain text password against stored bcrypt hash. Used during login."""
    return pwd_context.verify(plain, hashed)


# ─── JWT Token Creation ──────────────────────────────────────

def create_access_token(user: User) -> str:
    """
    Short-lived token (15 min default).
    Contains: user_id, role, expiry, type="access"
    Sent with every API request in the Authorization header.
    """
    expire = datetime.utcnow() + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user.id),       # "sub" = subject = who this token belongs to
        "role": user.role,
        "exp": expire,              # expiry time — jose auto-checks this
        "iat": datetime.utcnow(),   # issued at
        "type": "access",           # so we can tell access vs refresh apart
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user: User) -> str:
    """
    Long-lived token (7 days default).
    Only used to get a new access token when the old one expires.
    Contains: user_id, expiry, type="refresh"
    """
    expire = datetime.utcnow() + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(user.id),
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "refresh",
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_tokens(user: User) -> dict:
    """Create both access and refresh tokens at once."""
    return {
        "access_token": create_access_token(user),
        "refresh_token": create_refresh_token(user),
        "token_type": "bearer",
    }


# ─── Register ────────────────────────────────────────────────

async def register_patient(
    db: AsyncSession,
    email: str,
    password: str,
    full_name: str,
    date_of_birth: date,
    gender: str,
    phone: Optional[str] = None,
    abha_id: Optional[str] = None,
) -> dict:
    """
    Register a new patient. Creates 3 GO records:
    1. users row (login credentials)
    2. patients row (medical profile)
    3. patient_relationships row (self-relationship, auto-approved)

    Returns: tokens + IDs so the user is immediately logged in.
    """
    # Step 1: Check if email already taken
    existing = await UserModel.get_by_email(db, email)
    if existing:
        raise ValueError("Email already registered")

    # Step 2: Create user (GO)
    user = await UserModel.create(
        db,
        email=email,
        full_name=full_name,
        role="patient",
        password_hash=hash_password(password),
        phone=phone,
    )

    # Step 3: Create patient profile (GO)
    patient = await PatientModel.create(
        db,
        user_id=user.id,
        date_of_birth=date_of_birth,
        gender=gender,
        abha_id=abha_id,
    )

    # Step 4: Create self-relationship (GO) — auto-approved
    # This lets the patient book appointments for themselves
    await RelationshipModel.create(
        db,
        booker_patient_id=patient.id,
        beneficiary_patient_id=patient.id,
        relationship_type="self",
    )

    # Step 5: Commit all 3 inserts together (atomic transaction)
    await db.commit()

    # Step 6: Return tokens so user is immediately logged in
    tokens = create_tokens(user)
    return {
        **tokens,
        "user_id": str(user.id),
        "patient_id": str(patient.id),
        "role": user.role,
    }


# ─── Login ───────────────────────────────────────────────────

async def login(db: AsyncSession, email: str, password: str) -> dict:
    """
    Email/password login.
    Finds user → verifies password → returns tokens.
    """
    # Step 1: Find user by email
    user = await UserModel.get_by_email(db, email)
    if not user:
        raise ValueError("Invalid email or password")

    # Step 2: Check if this account uses password login (not Google-only)
    if not user.password_hash:
        raise ValueError("This account uses Google login. Please sign in with Google.")

    # Step 3: Verify password against stored bcrypt hash
    if not verify_password(password, user.password_hash):
        raise ValueError("Invalid email or password")

    # Step 4: Create tokens
    tokens = create_tokens(user)

    # Step 5: Get patient_id if user is a patient (needed by frontend)
    patient_id = None
    if user.role == "patient":
        patient = await PatientModel.get_by_user_id(db, user.id)
        if patient:
            patient_id = str(patient.id)

    return {
        **tokens,
        "user_id": str(user.id),
        "patient_id": patient_id,
        "role": user.role,
    }


# ─── Token Refresh ───────────────────────────────────────────

async def refresh_access_token(db: AsyncSession, refresh_token: str) -> dict:
    """
    Exchange a valid refresh token for a new access token.
    The refresh token itself is NOT rotated — it stays valid until it expires.
    """
    try:
        # Decode the refresh token
        payload = jwt.decode(
            refresh_token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )

        # Must be a refresh token, not an access token
        if payload.get("type") != "refresh":
            raise ValueError("Invalid token type")

        user_id = payload.get("sub")
        if not user_id:
            raise ValueError("Invalid token")

    except Exception:
        raise ValueError("Invalid or expired refresh token")

    # Load user from DB (they might have been deactivated since the token was issued)
    user = await UserModel.get_by_id(db, UUID(user_id))
    if not user:
        raise ValueError("User not found")

    # Return only a new access token (not a new refresh token)
    return {
        "access_token": create_access_token(user),
        "token_type": "bearer",
    }
