-- Migration 008: waitlist (LO)
-- Depends on: sessions, patients
-- When all slot positions are taken, patient goes here.
-- Auto-promoted when a cancellation frees a spot.

CREATE TABLE waitlist (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id              UUID NOT NULL REFERENCES sessions(id),
    patient_id              UUID NOT NULL REFERENCES patients(id),           -- Beneficiary
    booked_by_patient_id    UUID NOT NULL REFERENCES patients(id),           -- Booker
    priority_tier           VARCHAR(10) NOT NULL CHECK (
        priority_tier IN ('NORMAL', 'HIGH', 'CRITICAL')
    ),
    status                  VARCHAR(20) NOT NULL DEFAULT 'waiting' CHECK (
        status IN ('waiting', 'promoted', 'expired', 'cancelled')
    ),
    promoted_at             TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- One waitlist entry per patient per session
    UNIQUE(session_id, patient_id)
);

CREATE INDEX idx_waitlist_session_status ON waitlist(session_id, status);
CREATE INDEX idx_waitlist_promotion_order ON waitlist(session_id, status, priority_tier DESC, created_at ASC);
