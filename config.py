"""
Environment configuration via Pydantic BaseSettings.
Reads from .env file automatically.
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ─── PostgreSQL ───────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/dpms_v2"

    # ─── JWT ──────────────────────────────────────────────
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ─── Google OAuth ─────────────────────────────────────
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://127.0.0.1:8000/api/auth/google/callback"

    # ─── Email Adapter (Gmail SMTP) ────────────────────────
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""          # your-gmail@gmail.com
    SMTP_PASSWORD: str = ""          # Gmail App Password (not regular password)
    EMAIL_FROM_NAME: str = "HMS Hospital"

    # ─── SMS Adapter (Twilio) ─────────────────────────────
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_NUMBER: str = ""

    # ─── ABHA / UHID ─────────────────────────────────────
    ABHA_API_URL: str = "http://localhost:8001/api/abha"
    ABHA_API_KEY: str = "dummy-key-local"

    # ─── OpenAI ───────────────────────────────────────────
    OPENAI_API_KEY: str = ""
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"

    # ─── MongoDB ──────────────────────────────────────────
    MONGODB_URL: str = "mongodb://localhost:27017"
    MONGODB_DATABASE: str = "dpms_v2_chat"

    # ─── ChromaDB ─────────────────────────────────────────
    CHROMA_PERSIST_DIRECTORY: str = "./chroma_data"

    # ─── App ──────────────────────────────────────────────
    APP_NAME: str = "DPMS_v2"
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance — loaded once, reused everywhere."""
    return Settings()
