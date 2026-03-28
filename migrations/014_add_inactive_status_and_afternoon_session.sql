-- Migration 014: Add 'inactive' session status + Dr. Ananya afternoon session
-- Allows doctors to have sessions visible on dashboard even when not yet activated

-- Step 1: Add 'inactive' to allowed session statuses
ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_status_check;
ALTER TABLE sessions ADD CONSTRAINT sessions_status_check
    CHECK (status IN ('active', 'inactive', 'cancelled', 'completed'));

-- Step 2: Insert Dr. Ananya's afternoon session as inactive
INSERT INTO sessions (id, doctor_id, session_date, start_time, end_time, slot_duration_minutes, max_patients_per_slot, scheduling_type, total_slots, booked_count, status)
VALUES (
    '20000000-0000-0000-0000-000000000007',
    'f0000000-0000-0000-0000-000000000001',
    CURRENT_DATE,
    '14:00',
    '17:00',
    15,
    2,
    'TIME_SLOT',
    12,
    0,
    'inactive'
)
ON CONFLICT (id) DO UPDATE SET status = 'inactive';
