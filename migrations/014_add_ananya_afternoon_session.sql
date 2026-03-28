-- Add afternoon session for Dr. Ananya (General Medicine) — today 14:00-17:00
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
    'active'
)
ON CONFLICT (id) DO NOTHING;
