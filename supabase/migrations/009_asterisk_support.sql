-- Migration to support Asterisk & Multi-provider calls

-- 1. Alter calls table to make twilio_call_sid nullable (as Asterisk calls won't have it)
ALTER TABLE calls ALTER COLUMN twilio_call_sid DROP NOT NULL;

-- 2. Add columns for provider, call_uuid, caller_id, dialed_number, duration_seconds
ALTER TABLE calls ADD COLUMN IF NOT EXISTS call_uuid TEXT UNIQUE;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS provider TEXT DEFAULT 'twilio';
ALTER TABLE calls ADD COLUMN IF NOT EXISTS caller_id TEXT;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS dialed_number TEXT;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS duration_seconds INT DEFAULT 0;
