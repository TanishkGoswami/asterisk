-- Migration 019: Outbound dial safety and kill switches tracking

-- 1. Add dry_run column to batch_call_runs
ALTER TABLE public.batch_call_runs 
ADD COLUMN IF NOT EXISTS dry_run BOOLEAN DEFAULT false;

-- 2. Add safety tracking columns to batch_call_items
ALTER TABLE public.batch_call_items 
ADD COLUMN IF NOT EXISTS safety_result JSONB,
ADD COLUMN IF NOT EXISTS safety_reason_code TEXT,
ADD COLUMN IF NOT EXISTS safety_blocked_at TIMESTAMPTZ;

-- 3. Create outbound_safety_events table for auditing blocked dials
CREATE TABLE IF NOT EXISTS public.outbound_safety_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID,
    batch_run_id UUID,
    batch_item_id UUID,
    agent_id UUID,
    call_uuid TEXT,
    event_type TEXT,
    masked_phone_number TEXT,
    reason_code TEXT,
    safe_to_retry BOOLEAN,
    should_pause_campaign BOOLEAN,
    worker_instance_id TEXT,
    dry_run BOOLEAN,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 4. Reload PostgREST schema cache
NOTIFY pgrst, 'reload schema';
