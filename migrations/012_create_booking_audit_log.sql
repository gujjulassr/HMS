-- Migration 012: booking_audit_log (LO)
-- Depends on: appointments, users, patients
-- Complete audit trail. Every action creates an entry. Never deleted.

CREATE TABLE booking_audit_log (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action                  VARCHAR(20) NOT NULL CHECK (
        action IN ('book', 'cancel', 'reschedule', 'check_in', 'complete',
                   'no_show', 'waitlist_add', 'waitlist_promote')
    ),
    appointment_id          UUID REFERENCES appointments(id),   -- NULL for waitlist-only actions
    performed_by_user_id    UUID NOT NULL REFERENCES users(id),
    patient_id              UUID REFERENCES patients(id),
    metadata                JSONB,                               -- Action-specific data
    ip_address              INET,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_log_appointment ON booking_audit_log(appointment_id);
CREATE INDEX idx_audit_log_user ON booking_audit_log(performed_by_user_id);
CREATE INDEX idx_audit_log_action ON booking_audit_log(action, created_at DESC);
