"""
Shared FastAPI dependencies for authentication and authorization.
"""
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from go.models.patient import Patient, PatientModel
from go.models.user import User, UserModel

settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def get_current_user(
	token: str = Depends(oauth2_scheme),
	db: AsyncSession = Depends(get_db),
) -> User:
	"""
	Resolve the authenticated user from a Bearer JWT access token.
	"""
	credentials_exception = HTTPException(
		status_code=status.HTTP_401_UNAUTHORIZED,
		detail="Invalid or expired authentication token",
		headers={"WWW-Authenticate": "Bearer"},
	)

	try:
		payload = jwt.decode(
			token,
			settings.JWT_SECRET_KEY,
			algorithms=[settings.JWT_ALGORITHM],
		)
		if payload.get("type") != "access":
			raise credentials_exception

		user_sub = payload.get("sub")
		if not user_sub:
			raise credentials_exception

		user_id = UUID(str(user_sub))
		user = await UserModel.get_by_id(db, user_id)
		if user is None:
			raise credentials_exception
		return user
	except Exception:
		raise credentials_exception


async def get_current_patient(
	user: User = Depends(get_current_user),
	db: AsyncSession = Depends(get_db),
) -> Patient:
	"""
	Resolve patient profile for an authenticated user with patient role.
	"""
	if user.role != "patient":
		raise HTTPException(
			status_code=status.HTTP_403_FORBIDDEN,
			detail="Forbidden: patient role required",
		)

	patient = await PatientModel.get_by_user_id(db, user.id)
	if patient is None:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail="Patient profile not found",
		)
	return patient


def require_role(*roles: str):
	"""
	Factory for role-based access control dependencies.
	"""

	async def role_dependency(user: User = Depends(get_current_user)) -> User:
		if user.role not in roles:
			raise HTTPException(
				status_code=status.HTTP_403_FORBIDDEN,
				detail=f"Forbidden: requires one of {', '.join(roles)}",
			)
		return user

	return role_dependency
