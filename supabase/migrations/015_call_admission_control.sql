-- Migration 015: Call Admission Control and limits enforcement

-- 1. Create call_limit_events table
CREATE TABLE IF NOT EXISTS public.call_limit_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID,
  agent_id UUID,
  sip_trunk_provider_id UUID,
  did_number_id UUID,
  call_uuid TEXT,
  direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
  reason TEXT NOT NULL,
  caller_id TEXT,
  dialed_number TEXT,
  destination_number TEXT,
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 2. Create workspace_usage_counters table
CREATE TABLE IF NOT EXISTS public.workspace_usage_counters (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  billing_month TEXT NOT NULL,
  used_seconds INTEGER DEFAULT 0,
  used_minutes NUMERIC DEFAULT 0,
  estimated_cost NUMERIC DEFAULT 0,
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(workspace_id, billing_month)
);

-- 3. Safely update workspace_limits table if missing column defaults
-- Note: workspace_limits table already created in 012_admin_panel.sql, but we ensure columns are there and have defaults
ALTER TABLE public.workspace_limits ADD COLUMN IF NOT EXISTS monthly_minute_limit INTEGER DEFAULT 1000;
ALTER TABLE public.workspace_limits ADD COLUMN IF NOT EXISTS max_concurrent_calls INTEGER DEFAULT 1;
ALTER TABLE public.workspace_limits ADD COLUMN IF NOT EXISTS inbound_enabled BOOLEAN DEFAULT true;
ALTER TABLE public.workspace_limits ADD COLUMN IF NOT EXISTS outbound_enabled BOOLEAN DEFAULT true;
ALTER TABLE public.workspace_limits ADD COLUMN IF NOT EXISTS billing_status TEXT DEFAULT 'active' CHECK (billing_status IN ('trial', 'active', 'overdue', 'suspended'));

-- 4. Safely check/add max_concurrent_calls to sip_trunk_providers
ALTER TABLE public.sip_trunk_providers ADD COLUMN IF NOT EXISTS max_concurrent_calls INTEGER DEFAULT 10;

-- 5. Add max_concurrent_calls to agents
ALTER TABLE public.agents ADD COLUMN IF NOT EXISTS max_concurrent_calls INTEGER DEFAULT NULL;

-- 6. Add columns to calls table
ALTER TABLE public.calls ADD COLUMN IF NOT EXISTS sip_trunk_provider_id UUID REFERENCES public.sip_trunk_providers(id) ON DELETE SET NULL;
ALTER TABLE public.calls ADD COLUMN IF NOT EXISTS rejection_reason TEXT;
ALTER TABLE public.calls ADD COLUMN IF NOT EXISTS hangup_reason TEXT;
ALTER TABLE public.calls ADD COLUMN IF NOT EXISTS estimated_cost NUMERIC DEFAULT 0;

-- Enable RLS on new tables
ALTER TABLE public.call_limit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspace_usage_counters ENABLE ROW LEVEL SECURITY;
