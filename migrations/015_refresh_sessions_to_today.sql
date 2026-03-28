-- Migration 015: Refresh all session dates to TODAY
-- Run this anytime you want to reset test sessions to the current date
-- Safe to run multiple times

UPDATE sessions SET session_date = CURRENT_DATE
WHERE id IN (
    '20000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000003',
    '20000000-0000-0000-0000-000000000004',
    '20000000-0000-0000-0000-000000000005',
    '20000000-0000-0000-0000-000000000006'
);

UPDATE sessions SET session_date = CURRENT_DATE + 1
WHERE id = '20000000-0000-0000-0000-000000000002';

-- Verify
SELECT id, session_date, start_time, end_time, status
FROM sessions ORDER BY session_date, start_time;
