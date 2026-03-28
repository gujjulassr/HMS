-- Migration 014: Seed scheduling_config with clinic operational settings
-- These control booking validation, lunch hours, overtime limits

INSERT INTO scheduling_config (config_key, config_value, description) VALUES
-- Clinic operating hours
('clinic_open',            '"08:00"',   'Clinic opens — no sessions before this'),
('clinic_close',           '"18:00"',   'Clinic closes — no sessions/overtime after this'),

-- Lunch break — no bookings, no overtime overlap
('lunch_start',            '"12:30"',   'Lunch break starts — morning sessions must end by this'),
('lunch_end',              '"14:00"',   'Lunch break ends — afternoon sessions start from this'),

-- Overtime limits
('overtime_max_minutes',   '45',        'Max overtime a doctor can extend beyond scheduled end'),

-- Rate limiting
('max_bookings_per_day',   '5',         'Per-booker daily limit'),
('max_bookings_per_week',  '15',        'Per-booker weekly limit'),

-- Risk score
('risk_score_block_threshold', '7.0',   'Block booking if risk_score >= this'),
('risk_score_decay_daily',     '0.5',   'Nightly decay amount for positive risk scores');
