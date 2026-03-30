-- Migration 019: Fix unique constraint blocking multiple emergency patients
-- The constraint "uq_appointment_slot_active" was not dropped in 018.
-- Emergency patients all use slot_number=0 with incrementing slot_position,
-- so we need to drop the blanket unique constraint and rely on conditional indexes.

-- Drop ALL possible names for the unique constraint on (session_id, slot_number, slot_position)
ALTER TABLE appointments DROP CONSTRAINT IF EXISTS uq_appointment_slot_active;
ALTER TABLE appointments DROP CONSTRAINT IF EXISTS appointments_session_id_slot_number_slot_position_key;

-- Drop and recreate: unique only for regular patients (slot_number > 0)
DROP INDEX IF EXISTS idx_appointments_unique_slot;
CREATE UNIQUE INDEX IF NOT EXISTS idx_appointments_unique_slot
    ON appointments(session_id, slot_number, slot_position)
    WHERE slot_number > 0;

-- Unique emergency: same patient can't be added twice to same session as emergency
DROP INDEX IF EXISTS idx_appointments_unique_emergency;
CREATE UNIQUE INDEX IF NOT EXISTS idx_appointments_unique_emergency
    ON appointments(session_id, patient_id)
    WHERE slot_number = 0 AND status NOT IN ('cancelled', 'no_show');

-- Relax slot_position upper bound — emergency patients can have position > 3
ALTER TABLE appointments DROP CONSTRAINT IF EXISTS appointments_slot_position_check;
ALTER TABLE appointments ADD CONSTRAINT appointments_slot_position_check CHECK (slot_position >= 1);
