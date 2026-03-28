"""
GO Model: users
Long-lived identity — every person in the system.
Raw SQL via SQLAlchemy Core.
"""
from uuid import UUID
from datetime import datetime
from dataclasses import dataclass
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class User:
    id: UUID
    email: str
    phone: Optional[str]
    password_hash: Optional[str]
    full_name: str
    role: str  # patient, doctor, nurse, admin
    google_id: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserModel:

    @staticmethod
    async def create(
        db: AsyncSession,
        email: str,
        full_name: str,
        role: str,
        password_hash: Optional[str] = None,
        phone: Optional[str] = None,
        google_id: Optional[str] = None,
    ) -> User:
        result = await db.execute(
            text("""
                INSERT INTO users (email, full_name, role, password_hash, phone, google_id)
                VALUES (:email, :full_name, :role, :password_hash, :phone, :google_id)
                RETURNING *
            """),
            {
                "email": email,
                "full_name": full_name,
                "role": role,
                "password_hash": password_hash,
                "phone": phone,
                "google_id": google_id,
            },
        )
        row = result.mappings().one()
        return User(**row)

    @staticmethod
    async def get_by_id(db: AsyncSession, user_id: UUID) -> Optional[User]:
        result = await db.execute(
            text("SELECT * FROM users WHERE id = :id AND is_active = true"),
            {"id": user_id},
        )
        row = result.mappings().first()
        return User(**row) if row else None

    @staticmethod
    async def get_by_email(db: AsyncSession, email: str) -> Optional[User]:
        result = await db.execute(
            text("SELECT * FROM users WHERE email = :email AND is_active = true"),
            {"email": email},
        )
        row = result.mappings().first()
        return User(**row) if row else None

    @staticmethod
    async def get_by_google_id(db: AsyncSession, google_id: str) -> Optional[User]:
        result = await db.execute(
            text("SELECT * FROM users WHERE google_id = :google_id AND is_active = true"),
            {"google_id": google_id},
        )
        row = result.mappings().first()
        return User(**row) if row else None

    @staticmethod
    async def update(db: AsyncSession, user_id: UUID, **fields) -> Optional[User]:
        """Update specific fields. Pass only the fields you want to change."""
        if not fields:
            return await UserModel.get_by_id(db, user_id)
        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        fields["id"] = user_id
        result = await db.execute(
            text(f"UPDATE users SET {set_clause} WHERE id = :id RETURNING *"),
            fields,
        )
        row = result.mappings().first()
        return User(**row) if row else None

    @staticmethod
    async def deactivate(db: AsyncSession, user_id: UUID) -> bool:
        """Soft delete — set is_active = false."""
        result = await db.execute(
            text("UPDATE users SET is_active = false WHERE id = :id"),
            {"id": user_id},
        )
        return result.rowcount > 0
