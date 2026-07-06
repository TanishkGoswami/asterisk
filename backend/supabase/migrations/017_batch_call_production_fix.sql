-- ================================================================
-- MIGRATION 017: Batch Call System Production Fixes
-- ================================================================

-- 1. Safely drop inline status check constraints if they exist
DO $$
DECLARE
    r RECORD;
BEGIN
    -- Drop status constraints for batch_call_runs
    FOR r IN (
        SELECT conname 
        FROM pg_constraint 
        WHERE conrelid = 'public.batch_call_runs'::regclass AND conname LIKE '%status%'
    ) LOOP
        EXECUTE 'ALTER TABLE public.batch_call_runs DROP CONSTRAINT ' || quote_ident(r.conname);
    END LOOP;

    -- Drop status constraints for batch_call_items
    FOR r IN (
        SELECT conname 
        FROM pg_constraint 
        WHERE conrelid = 'public.batch_call_items'::regclass AND conname LIKE '%status%'
    ) LOOP
        EXECUTE 'ALTER TABLE public.batch_call_items DROP CONSTRAINT ' || quote_ident(r.conname);
    END LOOP;
END $$;

-- 2. Re-add status check constraints with extended statuses
ALTER TABLE public.batch_call_runs
  ADD CONSTRAINT batch_call_runs_status_check
  CHECK (status IN ('draft', 'pending', 'queued', 'running', 'paused', 'stopped', 'completed', 'cancelled', 'failed'));

ALTER TABLE public.batch_call_items
  ADD CONSTRAINT batch_call_items_status_check
  CHECK (status IN ('queued', 'dialing', 'connected', 'completed', 'no_answer', 'busy', 'failed', 'retry_later', 'cac_rejected', 'invalid_number', 'cancelled', 'rejected'));

-- 3. Add retry policy and locking columns to batch_call_items
ALTER TABLE public.batch_call_items ADD COLUMN IF NOT EXISTS attempt_count INTEGER DEFAULT 0;
ALTER TABLE public.batch_call_items ADD COLUMN IF NOT EXISTS max_attempts INTEGER DEFAULT 2;
ALTER TABLE public.batch_call_items ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ DEFAULT NULL;
ALTER TABLE public.batch_call_items ADD COLUMN IF NOT EXISTS last_error TEXT DEFAULT NULL;
ALTER TABLE public.batch_call_items ADD COLUMN IF NOT EXISTS last_cac_reason TEXT DEFAULT NULL;
ALTER TABLE public.batch_call_items ADD COLUMN IF NOT EXISTS locked_at TIMESTAMPTZ DEFAULT NULL;
ALTER TABLE public.batch_call_items ADD COLUMN IF NOT EXISTS reservation_id TEXT DEFAULT NULL;

-- 4. Add configuration and new counters to batch_call_runs
ALTER TABLE public.batch_call_runs ADD COLUMN IF NOT EXISTS max_parallel_calls INTEGER DEFAULT 1;
ALTER TABLE public.batch_call_runs ADD COLUMN IF NOT EXISTS attempted_count INTEGER DEFAULT 0;
ALTER TABLE public.batch_call_runs ADD COLUMN IF NOT EXISTS completed_count INTEGER DEFAULT 0;
ALTER TABLE public.batch_call_runs ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0;
ALTER TABLE public.batch_call_runs ADD COLUMN IF NOT EXISTS cancelled_count INTEGER DEFAULT 0;

-- 5. Create call_reservations table for persistent audit & stale recovery
CREATE TABLE IF NOT EXISTS public.call_reservations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_uuid TEXT NOT NULL UNIQUE,
    direction TEXT NOT NULL,
    workspace_id UUID NOT NULL,
    agent_id UUID NOT NULL,
    sip_trunk_provider_id UUID,
    did_number_id UUID,
    status TEXT DEFAULT 'reserved' CHECK (status IN ('reserved', 'released')),
    expires_at TIMESTAMPTZ NOT NULL,
    released_at TIMESTAMPTZ DEFAULT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_call_reservations_uuid ON public.call_reservations(call_uuid);
CREATE INDEX IF NOT EXISTS idx_call_reservations_status ON public.call_reservations(status);
