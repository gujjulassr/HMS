-- Migration 009: cancellation_log (LO)
-- Depends on: appointments, patients
-- Immutable record of every cancellation.
-- Stores the risk_delta that was added to the booker's risk_score.

CREATE TABLE cancellation_log (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    appointment_id              UUID NOT NULL REFERENCES appointments(id),
    cancelled_by_patient_id     UUID NOT NULL REFERENCES patients(id),  -- The booker who cancelled
    reason                      TEXT,
    risk_delta                  DECIMAL(4,2) NOT NULL,     -- 1.0 / max(hours_before, 0.5)
    hours_before_appointment    DECIMAL(6,2) NOT NULL,     -- Hours between cancel and appointment
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_cancellation_log_patient ON cancellation_log(cancelled_by_patient_id);
CREATE INDEX idx_cancellation_log_appointment ON cancellation_log(appointment_id);
-- For cooldown check: most recent cancellation by booker
CREATE INDEX idx_cancellation_log_recent ON cancellation_log(cancelled_by_patient_id, created_at DESC);
