-- Migration 002: patients (GO)
-- Depends on: users
-- Patient medical profile. One user has exactly one patient record.
-- risk_score tracks cancellation behavior (per booker, not per beneficiary)

CREATE TABLE patients (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID UNIQUE NOT NULL REFERENCES users(id),
    abha_id                 VARCHAR(14) UNIQUE,         -- UHID: 14-digit dummy for local project
    date_of_birth           DATE NOT NULL,               -- Critical: used to compute priority_tier
    gender                  VARCHAR(10) NOT NULL CHECK (gender IN ('male', 'female', 'other')),
    blood_group             VARCHAR(5),                  -- A+, B-, O+, etc.
    emergency_contact_name  VARCHAR(255),
    emergency_contact_phone VARCHAR(15),
    address                 TEXT,
    risk_score              DECIMAL(4,2) NOT NULL DEFAULT 0.00,  -- >=7.0 blocks bookings
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_patients_user_id ON patients(user_id);
CREATE INDEX idx_patients_abha_id ON patients(abha_id) WHERE abha_id IS NOT NULL;

CREATE TRIGGER trg_patients_updated_at
    BEFORE UPDATE ON patients
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
