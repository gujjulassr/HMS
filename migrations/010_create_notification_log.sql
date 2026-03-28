-- Migration 010: notification_log (LO)
-- Depends on: users, appointments
-- Tracks every notification sent through any adapter (email, SMS).

CREATE TABLE notification_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id),
    appointment_id  UUID REFERENCES appointments(id),       -- NULL for system-wide notifications
    type            VARCHAR(30) NOT NULL CHECK (
        type IN ('booking_confirmation', 'cancellation', 'reminder',
                 'waitlist_promotion', 'queue_update', 'relationship_request')
    ),
    channel         VARCHAR(10) NOT NULL CHECK (channel IN ('email', 'sms', 'push')),
    status          VARCHAR(10) NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'sent', 'failed')
    ),
    content         TEXT NOT NULL,
    error_message   TEXT,                                    -- Error details if status=failed
    sent_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_notification_log_user ON notification_log(user_id, created_at DESC);
CREATE INDEX idx_notification_log_pending ON notification_log(status) WHERE status = 'pending';
