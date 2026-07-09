-- Migration to support Production Admin Panel

-- 1. Add role to profiles
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS role TEXT DEFAULT 'user';

-- 2. Create admin_audit_logs table
CREATE TABLE IF NOT EXISTS public.admin_audit_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  admin_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  action TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT,
  details JSONB DEFAULT '{}'::jsonb,
  ip_address TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 3. Create workspace_limits table
CREATE TABLE IF NOT EXISTS public.workspace_limits (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE UNIQUE,
  monthly_minute_limit INTEGER DEFAULT 1000,
  max_concurrent_calls INTEGER DEFAULT 5,
  inbound_enabled BOOLEAN DEFAULT true,
  outbound_enabled BOOLEAN DEFAULT true,
  billing_status TEXT DEFAULT 'active' CHECK (billing_status IN ('trial', 'active', 'overdue', 'suspended')),
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- 4. Create billing_usage_snapshots table
CREATE TABLE IF NOT EXISTS public.billing_usage_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  year_month TEXT NOT NULL,
  stt_minutes NUMERIC DEFAULT 0.0,
  stt_cost NUMERIC DEFAULT 0.0,
  tts_characters INTEGER DEFAULT 0,
  tts_cost NUMERIC DEFAULT 0.0,
  llm_tokens_input INTEGER DEFAULT 0,
  llm_tokens_output INTEGER DEFAULT 0,
  llm_cost NUMERIC DEFAULT 0.0,
  sip_minutes NUMERIC DEFAULT 0.0,
  sip_cost NUMERIC DEFAULT 0.0,
  total_cost NUMERIC DEFAULT 0.0,
  plan_price NUMERIC DEFAULT 0.0,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(workspace_id, year_month)
);

-- 5. Create system_health_checks table
CREATE TABLE IF NOT EXISTS public.system_health_checks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  checked_at TIMESTAMPTZ DEFAULT now(),
  status TEXT NOT NULL,
  details JSONB DEFAULT '{}'::jsonb
);

-- 6. Create encrypted_settings table
CREATE TABLE IF NOT EXISTS public.encrypted_settings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  key_name TEXT UNIQUE NOT NULL,
  encrypted_value TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Enable Row Level Security
ALTER TABLE public.admin_audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspace_limits ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_usage_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.system_health_checks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.encrypted_settings ENABLE ROW LEVEL SECURITY;
