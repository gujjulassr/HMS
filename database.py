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

        # Fix notification_log CHECK constraints — allow all types and channels we use
        await conn.execute(text("""
            DO $$ BEGIN
                ALTER TABLE notification_log DROP CONSTRAINT IF EXISTS notification_log_type_check;
                ALTER TABLE notification_log DROP CONSTRAINT IF EXISTS notification_log_channel_check;
            EXCEPTION WHEN undefined_object THEN NULL;
            END $$
        """))
        await conn.execute(text("""
            DO $$ BEGIN
                ALTER TABLE notification_log ADD CONSTRAINT notification_log_type_check CHECK (
                    type IN (
                        'booking_confirmation', 'cancellation', 'reminder',
                        'waitlist_promotion', 'queue_update', 'relationship_request',
                        'BOOKED_BY_STAFF', 'EMERGENCY_BOOKED', 'DELAY_UPDATE',
                        'CANNOT_BE_SEEN', 'YOUR_TURN', 'SESSION_CANCELLED'
                    )
                );
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$
        """))
        await conn.execute(text("""
            DO $$ BEGIN
                ALTER TABLE notification_log ADD CONSTRAINT notification_log_channel_check CHECK (
                    channel IN ('email', 'sms', 'push', 'in_app')
                );
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$
        """))
        # Replace absolute unique constraint on appointment slots with a partial
        # one that ignores cancelled rows — so a cancelled slot can be re-booked.
        await conn.execute(text(
            "ALTER TABLE appointments DROP CONSTRAINT IF EXISTS appointments_session_id_slot_number_slot_position_key"
        ))
        await conn.execute(text(
            "DROP INDEX IF EXISTS uq_appointment_slot_active"
        ))
        await conn.execute(text("""
            CREATE UNIQUE INDEX uq_appointment_slot_active
            ON appointments (session_id, slot_number, slot_position)
            WHERE status != 'cancelled'
        """))

        print("[DB] Auto-migrations applied")


async def close_db():
    """Called on shutdown to clean up connection pool."""
    await engine.dispose()
    print("[DB] Connection pool closed")
