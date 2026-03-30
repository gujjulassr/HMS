-- Migration 018: Allow emergency patients without a slot (slot_number = 0)
-- Emergency patients bypass the slot system entirely.
-- slot_number=0 means "no slot assigned — emergency walk-in"

-- Drop the old constraint that requires slot_number > 0
ALTER TABLE appointments DROP CONSTRAINT IF EXISTS appointments_slot_number_check;

-- Allow slot_number >= 0 (0 = emergency / no slot)
ALTER TABLE appointments ADD CONSTRAINT appointments_slot_number_check CHECK (slot_number >= 0);

-- Drop the old unique constraint — we need a conditional one
ALTER TABLE appointments DROP CONSTRAINT IF EXISTS appointments_session_id_slot_number_slot_position_key;

-- For regular patients (slot_number > 0): keep unique per session+slot+position
CREATE UNIQUE INDEX IF NOT EXISTS idx_appointments_unique_slot
    ON appointments(session_id, slot_number, slot_position)
    WHERE slot_number > 0;

-- For emergency patients (slot_number = 0): unique per session+patient (can't add same patient twice)
CREATE UNIQUE INDEX IF NOT EXISTS idx_appointments_unique_emergency
    ON appointments(session_id, patient_id)
    WHERE slot_number = 0;

-- Also allow slot_position beyond 3 for emergencies (they just use 1)
ALTER TABLE appointments DROP CONSTRAINT IF EXISTS appointments_slot_position_check;
ALTER TABLE appointments ADD CONSTRAINT appointments_slot_position_check CHECK (slot_position >= 1 AND slot_position <= 3);
