-- Migration 011: doctor_ratings (LO)
-- Depends on: appointments, patients, doctors
-- Post-visit feedback. One rating per appointment.
-- Review text gets embedded in ChromaDB for RAG.

CREATE TABLE doctor_ratings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    appointment_id  UUID UNIQUE NOT NULL REFERENCES appointments(id),  -- One rating per appointment
    patient_id      UUID NOT NULL REFERENCES patients(id),
    doctor_id       UUID NOT NULL REFERENCES doctors(id),              -- Denormalized for query speed
    rating          INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
    review          TEXT,
    sentiment_score DECIMAL(3,2),              -- Computed by OpenAI: -1.0 to 1.0
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_doctor_ratings_doctor ON doctor_ratings(doctor_id);
CREATE INDEX idx_doctor_ratings_patient ON doctor_ratings(patient_id);
