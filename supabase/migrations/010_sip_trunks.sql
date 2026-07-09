-- Migration to support SIP Trunk providers, DID numbers, and test results

-- 1. Create sip_trunk_providers table
CREATE TABLE IF NOT EXISTS sip_trunk_providers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  provider_type TEXT NOT NULL CHECK (provider_type IN ('airtel', 'jio', 'tata', 'twilio', 'exotel', 'myoperator', 'knowlarity', 'custom')),
  auth_type TEXT NOT NULL CHECK (auth_type IN ('ip_auth', 'username_password')),
  sip_proxy TEXT NOT NULL,
  sip_port INTEGER DEFAULT 5060,
  transport TEXT DEFAULT 'udp' CHECK (transport IN ('udp', 'tcp', 'tls')),
  username TEXT,
  password_encrypted TEXT,
  outbound_caller_id TEXT,
  provider_ips JSONB,
  allowed_codecs JSONB DEFAULT '["ulaw", "alaw"]'::jsonb,
  rtp_ip TEXT,
  max_concurrent_calls INTEGER DEFAULT 10,
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'active', 'disabled', 'error')),
  last_checked_at TIMESTAMPTZ,
  last_error TEXT,
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- 2. Create did_numbers table
CREATE TABLE IF NOT EXISTS did_numbers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  sip_trunk_provider_id UUID REFERENCES sip_trunk_providers(id) ON DELETE SET NULL,
  phone_number TEXT NOT NULL,
  country_code TEXT NOT NULL,
  label TEXT,
  provider TEXT,
  agent_id UUID REFERENCES agents(id) ON DELETE SET NULL,
  status TEXT DEFAULT 'active' CHECK (status IN ('active', 'disabled', 'pending')),
  inbound_enabled BOOLEAN DEFAULT true,
  outbound_enabled BOOLEAN DEFAULT false,
  recording_enabled BOOLEAN DEFAULT false,
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(workspace_id, phone_number)
);

-- 3. Create sip_trunk_test_results table
CREATE TABLE IF NOT EXISTS sip_trunk_test_results (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  sip_trunk_provider_id UUID NOT NULL REFERENCES sip_trunk_providers(id) ON DELETE CASCADE,
  test_type TEXT NOT NULL CHECK (test_type IN ('config_validation', 'dns_check', 'firewall_check', 'asterisk_reload', 'inbound_call', 'outbound_call')),
  status TEXT NOT NULL CHECK (status IN ('success', 'failed', 'pending')),
  result JSONB DEFAULT '{}'::jsonb,
  error TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 4. Alter calls table to make phone_number_id nullable and add did_number_id
ALTER TABLE calls ALTER COLUMN phone_number_id DROP NOT NULL;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS did_number_id UUID REFERENCES did_numbers(id) ON DELETE SET NULL;

-- Enable Row Level Security
ALTER TABLE sip_trunk_providers ENABLE ROW LEVEL SECURITY;
ALTER TABLE did_numbers ENABLE ROW LEVEL SECURITY;
ALTER TABLE sip_trunk_test_results ENABLE ROW LEVEL SECURITY;
