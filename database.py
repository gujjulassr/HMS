"""
PostgreSQL async connection pool via SQLAlchemy Core.
No ORM — raw SQL only. Every query goes through this pool.
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from config import get_settings

settings = get_settings()

# ─── Engine ───────────────────────────────────────────────
# pool_size=10: max 10 persistent connections
# max_overflow=20: up to 20 extra connections under load
# pool_pre_ping=True: test connection health before using
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=settings.APP_DEBUG,  # Log SQL in debug mode
)

# ─── Session Factory ─────────────────────────────────────
# expire_on_commit=False: keep data accessible after commit
async_session = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """
    FastAPI dependency: yields a database session.
    Auto-closes when the request finishes.

    Usage in routes:
        @router.get("/example")
        async def example(db: AsyncSession = Depends(get_db)):
            result = await db.execute(text("SELECT 1"))
    """
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """
    Called on startup to verify database connection and apply auto-migrations.
    Does NOT create tables — use migrations for that.
    """
    async with engine.begin() as conn:
        from sqlalchemy import text
        await conn.execute(text("SELECT 1"))
        print("[DB] Connection verified successfully")

        # ── Auto-migrations (safe to re-run) ──────────────────
        # Drop UNIQUE on phone — family members can share numbers
        await conn.execute(text(
            "ALTER TABLE users DROP CONSTRAINT IF EXISTS users_phone_key"
        ))
        # Drop UNIQUE on abha_id — same UHID may be re-submitted on profile save
        await conn.execute(text(
            "ALTER TABLE patients DROP CONSTRAINT IF EXISTS patients_abha_id_key"
        ))
        # Add google_id column if missing (for OAuth support)
        await conn.execute(text("""
            DO $$ BEGIN
                ALTER TABLE users ADD COLUMN google_id VARCHAR(255) UNIQUE;
            EXCEPTION WHEN duplicate_column THEN NULL;
            END $$
        """))
        print("[DB] Auto-migrations applied")


async def close_db():
    """Called on shutdown to clean up connection pool."""
    await engine.dispose()
    print("[DB] Connection pool closed")
