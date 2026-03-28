-- Migration 016: Widen audit action constraint + add duration_minutes to appointments
-- Safe to run multiple times (uses IF EXISTS / IF NOT EXISTS patterns)

-- 1) Drop the restrictive CHECK on booking_audit_log.action
--    Allow any action string so queue/session routes can log freely.
ALTER TABLE booking_audit_log DROP CONSTRAINT IF EXISTS booking_audit_log_action_check;
ALTER TABLE booking_audit_log ALTER COLUMN action TYPE VARCHAR(50);

-- 2) Add duration_minutes to appointments
--    Nurse can override per-patient; NULL = use session default slot_duration.
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS duration_minutes INTEGER;
