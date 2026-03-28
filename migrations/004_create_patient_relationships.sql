-- Migration 004: patient_relationships (GO)
-- Depends on: patients
-- Multi-beneficiary support. Links a booker to people they can book for.
-- Must be approved by beneficiary before use. Self-relationships auto-approve.

CREATE TABLE patient_relationships (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    booker_patient_id       UUID NOT NULL REFERENCES patients(id),
    beneficiary_patient_id  UUID NOT NULL REFERENCES patients(id),
    relationship_type       VARCHAR(20) NOT NULL CHECK (
        relationship_type IN ('self', 'spouse', 'child', 'parent', 'sibling', 'friend', 'other')
    ),
    is_approved             BOOLEAN NOT NULL DEFAULT false,  -- Beneficiary must approve
    approved_at             TIMESTAMPTZ,                      -- NULL until approved
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- No duplicate relationships
    UNIQUE(booker_patient_id, beneficiary_patient_id),

    -- Prevent self-referencing non-self relationships
    -- (booker can equal beneficiary ONLY when type = 'self')
    CHECK (
        (booker_patient_id = beneficiary_patient_id AND relationship_type = 'self')
        OR
        (booker_patient_id != beneficiary_patient_id AND relationship_type != 'self')
    )
);

CREATE INDEX idx_relationships_booker ON patient_relationships(booker_patient_id);
CREATE INDEX idx_relationships_beneficiary ON patient_relationships(beneficiary_patient_id);
