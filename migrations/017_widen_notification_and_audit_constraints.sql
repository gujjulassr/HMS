-- Migration 017: Widen notification_log & booking_audit_log constraints
-- Safe to run multiple times (uses DROP IF EXISTS)

-- 1) notification_log.type — allow any type string (SESSION_CANCELLED, NO_SHOW, SESSION_ENDED, etc.)
ALTER TABLE notification_log DROP CONSTRAINT IF EXISTS notification_log_type_check;
ALTER TABLE notification_log ALTER COLUMN type TYPE VARCHAR(50);

-- 2) notification_log.channel — add 'in_app' channel
ALTER TABLE notification_log DROP CONSTRAINT IF EXISTS notification_log_channel_check;
ALTER TABLE notification_log ADD CONSTRAINT notification_log_channel_check
    CHECK (channel IN ('email', 'sms', 'push', 'in_app'));

-- 3) booking_audit_log.action — drop restrictive CHECK (may already be done by 016)
ALTER TABLE booking_audit_log DROP CONSTRAINT IF EXISTS booking_audit_log_action_check;
ALTER TABLE booking_audit_log ALTER COLUMN action TYPE VARCHAR(50);
