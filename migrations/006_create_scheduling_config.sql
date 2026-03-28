-- Migration 006: scheduling_config (GO)
-- Depends on: users (for updated_by)
-- System-wide configuration as key-value pairs.
-- Loaded at the start of every booking/cancel operation.

CREATE TABLE scheduling_config (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    config_key      VARCHAR(100) UNIQUE NOT NULL,
    config_value    JSONB NOT NULL,
    description     TEXT,
    updated_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_scheduling_config_updated_at
    BEFORE UPDATE ON scheduling_config
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ─── Seed default configuration ──────────────────────────
INSERT INTO scheduling_config (config_key, config_value, description) VALUES
    ('max_bookings_per_day', '5', 'Maximum bookings a single booker can make per day'),
    ('max_bookings_per_week', '15', 'Maximum bookings a single booker can make per week'),
    ('cancel_cooldown_hours', '2', 'Hours a booker must wait between cancellations'),
    ('risk_score_threshold', '7.0', 'Risk score at or above which a booker is blocked'),
    ('risk_decay_per_day', '0.1', 'Amount risk score decreases per day via nightly cron');
