-- ================================================================
-- COMBINED MIGRATION: 015 + 016
-- Run this entire script in Supabase SQL Editor.
-- All statements use IF NOT EXISTS / IF EXISTS for safety.
-- ================================================================

-- ================================================================
-- MIGRATION 015: Call Admission Control
-- ================================================================

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

-- 3. Add workspace_limits columns safely
ALTER TABLE public.workspace_limits ADD COLUMN IF NOT EXISTS monthly_minute_limit INTEGER DEFAULT 1000;
ALTER TABLE public.workspace_limits ADD COLUMN IF NOT EXISTS max_concurrent_calls INTEGER DEFAULT 1;
ALTER TABLE public.workspace_limits ADD COLUMN IF NOT EXISTS inbound_enabled BOOLEAN DEFAULT true;
ALTER TABLE public.workspace_limits ADD COLUMN IF NOT EXISTS outbound_enabled BOOLEAN DEFAULT true;

-- Add billing_status only if it doesn't exist (check constraint added separately below)
ALTER TABLE public.workspace_limits ADD COLUMN IF NOT EXISTS billing_status TEXT DEFAULT 'active';

-- Safely add or replace the check constraint on billing_status
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'workspace_limits_billing_status_check'
  ) THEN
    ALTER TABLE public.workspace_limits
      ADD CONSTRAINT workspace_limits_billing_status_check
      CHECK (billing_status IN ('trial', 'active', 'overdue', 'suspended'));
  END IF;
END$$;

-- 4. Add max_concurrent_calls to sip_trunk_providers
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


-- ================================================================
-- MIGRATION 016: Admin Production Safety
-- ================================================================

-- 1. Create admin_audit_logs if missing
CREATE TABLE IF NOT EXISTS public.admin_audit_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_user_id uuid,
    action text NOT NULL,
    target_type text,
    target_id text,
    old_value jsonb DEFAULT '{}',
    new_value jsonb DEFAULT '{}',
    metadata jsonb DEFAULT '{}',
    ip_address text,
    user_agent text,
    created_at timestamptz DEFAULT now()
);

-- Ensure all columns exist in case table was created previously with fewer columns
ALTER TABLE public.admin_audit_logs ADD COLUMN IF NOT EXISTS admin_user_id uuid;
ALTER TABLE public.admin_audit_logs ADD COLUMN IF NOT EXISTS action text;
ALTER TABLE public.admin_audit_logs ADD COLUMN IF NOT EXISTS target_type text;
ALTER TABLE public.admin_audit_logs ADD COLUMN IF NOT EXISTS target_id text;
ALTER TABLE public.admin_audit_logs ADD COLUMN IF NOT EXISTS old_value jsonb DEFAULT '{}';
ALTER TABLE public.admin_audit_logs ADD COLUMN IF NOT EXISTS new_value jsonb DEFAULT '{}';
ALTER TABLE public.admin_audit_logs ADD COLUMN IF NOT EXISTS metadata jsonb DEFAULT '{}';
ALTER TABLE public.admin_audit_logs ADD COLUMN IF NOT EXISTS ip_address text;
ALTER TABLE public.admin_audit_logs ADD COLUMN IF NOT EXISTS user_agent text;
ALTER TABLE public.admin_audit_logs ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_user_date ON public.admin_audit_logs (admin_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_action_date ON public.admin_audit_logs (action, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_target ON public.admin_audit_logs (target_type, target_id);

-- 2. Create asterisk_config_versions if missing
CREATE TABLE IF NOT EXISTS public.asterisk_config_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_number integer NOT NULL,
    config_type text NOT NULL,
    pjsip_config text,
    extensions_config text,
    metadata jsonb DEFAULT '{}',
    generated_by uuid,
    validation_status text DEFAULT 'pending',
    validation_error text,
    reload_status text DEFAULT 'not_reloaded',
    reload_error text,
    registration_status text DEFAULT 'healthy' CHECK (registration_status IN ('healthy', 'warning', 'failed')),
    registration_warning text,
    rollback_available boolean DEFAULT true,
    is_active boolean DEFAULT false,
    rollback_of uuid,
    created_at timestamptz DEFAULT now(),
    applied_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_asterisk_config_versions_num ON public.asterisk_config_versions (version_number);
CREATE INDEX IF NOT EXISTS idx_asterisk_config_versions_active ON public.asterisk_config_versions (is_active);
CREATE INDEX IF NOT EXISTS idx_asterisk_config_versions_date ON public.asterisk_config_versions (created_at DESC);

-- 3. Create provider_health_events if missing
CREATE TABLE IF NOT EXISTS public.provider_health_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider text NOT NULL,
    service_type text NOT NULL,
    status text NOT NULL CHECK (status IN ('success', 'failure', '429_rate_limited')),
    latency_ms integer,
    error_code text,
    error_message text,
    workspace_id uuid,
    agent_id uuid,
    call_uuid text,
    metadata jsonb DEFAULT '{}',
    created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_provider_health_prov ON public.provider_health_events (provider, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_provider_health_srv ON public.provider_health_events (service_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_provider_health_stat ON public.provider_health_events (status, created_at DESC);

-- 4. Create batch_call_runs if missing
CREATE TABLE IF NOT EXISTS public.batch_call_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL,
    agent_id uuid,
    status text DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'paused', 'stopped', 'completed')),
    total_numbers integer DEFAULT 0,
    queued_count integer DEFAULT 0,
    dialed_count integer DEFAULT 0,
    connected_count integer DEFAULT 0,
    failed_count integer DEFAULT 0,
    rejected_count integer DEFAULT 0,
    cac_rejected_count integer DEFAULT 0,
    estimated_cost numeric DEFAULT 0,
    started_at timestamptz,
    ended_at timestamptz,
    created_at timestamptz DEFAULT now(),
    metadata jsonb DEFAULT '{}'
);

-- 5. Create batch_call_items if missing
CREATE TABLE IF NOT EXISTS public.batch_call_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_run_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    agent_id uuid,
    phone_number text NOT NULL,
    call_uuid text,
    status text DEFAULT 'queued' CHECK (status IN ('queued', 'dialing', 'connected', 'failed', 'rejected', 'cac_rejected')),
    rejection_reason text,
    failure_reason text,
    started_at timestamptz,
    ended_at timestamptz,
    created_at timestamptz DEFAULT now(),
    metadata jsonb DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_batch_call_items_run ON public.batch_call_items (batch_run_id);
CREATE INDEX IF NOT EXISTS idx_batch_call_items_workspace ON public.batch_call_items (workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_batch_call_items_status ON public.batch_call_items (status);

-- 6. Add tracking columns to existing tables
ALTER TABLE public.sip_trunk_providers
  ADD COLUMN IF NOT EXISTS created_by uuid,
  ADD COLUMN IF NOT EXISTS updated_by uuid;

ALTER TABLE public.did_numbers
  ADD COLUMN IF NOT EXISTS created_by uuid,
  ADD COLUMN IF NOT EXISTS updated_by uuid;

ALTER TABLE public.workspace_limits
  ADD COLUMN IF NOT EXISTS updated_by uuid;

-- ================================================================
-- FIX: Update agents.voice_provider check constraint
-- Add sarvam and cartesia to allowed providers
-- ================================================================
DO $$
BEGIN
  -- Drop old constraint if it exists (ignores error if not present)
  ALTER TABLE public.agents DROP CONSTRAINT IF EXISTS agents_voice_provider_check;
EXCEPTION WHEN OTHERS THEN
  NULL;
END$$;

ALTER TABLE public.agents
  ADD CONSTRAINT agents_voice_provider_check
  CHECK (voice_provider IN ('elevenlabs', 'openai', 'deepgram', 'google', 'azure', 'aws', 'sarvam', 'cartesia'));
