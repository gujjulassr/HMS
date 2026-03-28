-- Migration 005: sessions (GO)
-- Depends on: doctors
-- Doctor availability windows. A session is a time block divided into slots.
-- On-the-fly availability: available = total_slots * max_patients_per_slot - booked_count
-- NO pre-generated slot rows.

CREATE TABLE sessions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doctor_id               UUID NOT NULL REFERENCES doctors(id),
    session_date            DATE NOT NULL,
    start_time              TIME NOT NULL,
    end_time                TIME NOT NULL,
    slot_duration_minutes   INTEGER NOT NULL DEFAULT 15,
    max_patients_per_slot   INTEGER NOT NULL DEFAULT 2,  -- Overrides doctor default per session
    scheduling_type         VARCHAR(20) NOT NULL DEFAULT 'TIME_SLOT' CHECK (
        scheduling_type IN ('TIME_SLOT', 'FCFS', 'PRIORITY_QUEUE')
    ),
    total_slots             INTEGER NOT NULL,             -- Computed on insert: (end - start) / duration
    booked_count            INTEGER NOT NULL DEFAULT 0,   -- Counter cache, updated on book/cancel
    -- Real-time tracking: doctor arrival & overtime
    doctor_checkin_at       TIMESTAMPTZ,                     -- When doctor actually starts seeing patients
    actual_end_time         TIME,                            -- If doctor stays late (overtime) or leaves early
    delay_minutes           INTEGER DEFAULT 0,               -- Auto-computed: checkin - start_time (in minutes)
    notes                   TEXT,                             -- "Doctor running 30 min late", "Extended by 2 slots"

    status                  VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (
        status IN ('active', 'cancelled', 'completed')
    ),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- No overlapping sessions for same doctor
    UNIQUE(doctor_id, session_date, start_time),

    -- end_time must be after start_time
    CHECK (end_time > start_time),

    -- total_slots must be positive
    CHECK (total_slots > 0),

    -- booked_count cannot exceed capacity
    CHECK (booked_count >= 0)
);

CREATE INDEX idx_sessions_doctor_date ON sessions(doctor_id, session_date);
CREATE INDEX idx_sessions_status ON sessions(status) WHERE status = 'active';

CREATE TRIGGER trg_sessions_updated_at
    BEFORE UPDATE ON sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
