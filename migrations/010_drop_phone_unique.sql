-- Migration 010: Remove UNIQUE constraint on phone
-- Reason: family members can share a phone number, and walk-in patients
-- registered by staff may not have a phone at all (NULL duplicates).

ALTER TABLE users DROP CONSTRAINT IF EXISTS users_phone_key;
DROP INDEX IF EXISTS users_phone_key;

-- Keep a regular index for lookups, just not unique
CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone) WHERE phone IS NOT NULL;
