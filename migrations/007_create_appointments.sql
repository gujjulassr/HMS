-- Migration 007: appointments (LO)
-- Depends on: sessions, patients, users
-- The core transaction table. Created per booking.
-- Lifecycle: booked → checked_in → in_progress → completed
-- UNIQUE(session_id, slot_number, slot_position) prevents double-booking

CREATE TABLE appointments (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id              UUID NOT NULL REFERENCES sessions(id),
    patient_id              UUID NOT NULL REFERENCES patients(id),           -- BENEFICIARY
    booked_by_patient_id    UUID NOT NULL REFERENCES patients(id),           -- BOOKER
    slot_number             INTEGER NOT NULL,              -- Which slot (1 to total_slots)
    slot_position           INTEGER NOT NULL,              -- 1 = original, 2 = overbook
    priority_tier           VARCHAR(10) NOT NULL CHECK (
        priority_tier IN ('NORMAL', 'HIGH', 'CRITICAL')
    ),                                                      -- Auto from DOB, IMMUTABLE
    visual_priority         INTEGER NOT NULL DEFAULT 5 CHECK (
        visual_priority >= 1 AND visual_priority <= 10
    ),                                                      -- Nurse sets at check-in
    is_emergency            BOOLEAN NOT NULL DEFAULT FALSE,  -- Emergency override by admin/staff
    status                  VARCHAR(20) NOT NULL DEFAULT 'booked' CHECK (
        status IN ('booked', 'checked_in', 'in_progress', 'completed', 'cancelled', 'no_show')
    ),
    checked_in_at           TIMESTAMPTZ,
    checked_in_by           UUID REFERENCES users(id),     -- Nurse who checked in
    completed_at            TIMESTAMPTZ,
    notes                   TEXT,                           -- Doctor notes post-consultation
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Prevent double-booking same slot position
    UNIQUE(session_id, slot_number, slot_position),

    -- slot_position: 1 = original, 2 = overbook, 3 = emergency override
    CHECK (slot_position IN (1, 2, 3)),

    -- slot_number must be positive
    CHECK (slot_number > 0)
);

-- Queue ordering query uses this index heavily
CREATE INDEX idx_appointments_queue ON appointments(session_id, status, priority_tier DESC, visual_priority DESC, created_at ASC);
CREATE INDEX idx_appointments_session_status ON appointments(session_id, status);
CREATE INDEX idx_appointments_patient ON appointments(patient_id);
CREATE INDEX idx_appointments_booked_by ON appointments(booked_by_patient_id);

CREATE TRIGGER trg_appointments_updated_at
    BEFORE UPDATE ON appointments
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
