-- Migration 003: doctors (GO)
-- Depends on: users
-- Doctor profile and consultation settings
-- max_patients_per_slot is the DEFAULT for new sessions (can be overridden per session)

CREATE TABLE doctors (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID UNIQUE NOT NULL REFERENCES users(id),
    specialization          VARCHAR(255) NOT NULL,       -- e.g., Cardiology, Dermatology
    qualification           VARCHAR(255) NOT NULL,       -- e.g., MBBS, MD
    license_number          VARCHAR(50) UNIQUE NOT NULL, -- Medical license for verification
    consultation_fee        DECIMAL(10,2) NOT NULL,      -- Fee in INR
    max_patients_per_slot   INTEGER NOT NULL DEFAULT 2,  -- 2 = original + 1 overbook
    is_available            BOOLEAN NOT NULL DEFAULT true,-- Master toggle
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_doctors_user_id ON doctors(user_id);
CREATE INDEX idx_doctors_specialization ON doctors(specialization);

CREATE TRIGGER trg_doctors_updated_at
    BEFORE UPDATE ON doctors
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
