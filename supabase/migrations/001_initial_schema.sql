-- 1. CORE TENANT TABLES

CREATE TABLE profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email TEXT NOT NULL UNIQUE,
  name TEXT,
  avatar_url TEXT,
  subscription_tier TEXT DEFAULT 'free',
  billing_email TEXT,
  billing_address JSONB,
  stripe_customer_id TEXT UNIQUE,
  timezone TEXT DEFAULT 'UTC',
  preferences JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE TABLE workspaces (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  owner_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  call_limit INT DEFAULT 1000,
  concurrent_call_limit INT DEFAULT 10,
  current_concurrent_calls INT DEFAULT 0,
  storage_limit_gb INT DEFAULT 100,
  storage_used_gb DECIMAL(10, 2) DEFAULT 0,
  timezone TEXT DEFAULT 'UTC',
  billing_email TEXT,
  webhook_url TEXT,
  slack_webhook TEXT,
  status TEXT DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'deleted')),
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE TABLE workspace_members (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  role TEXT DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(workspace_id, user_id)
);

CREATE TABLE agents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  avatar_url TEXT,
  status TEXT DEFAULT 'inactive' CHECK (status IN ('active', 'inactive', 'training')),
  model TEXT NOT NULL DEFAULT 'gpt-4-turbo',
  system_prompt TEXT NOT NULL,
  temperature DECIMAL(3, 2) DEFAULT 0.7 CHECK (temperature BETWEEN 0 AND 2),
  max_tokens INT DEFAULT 150,
  voice_id TEXT NOT NULL DEFAULT 'en-US-Neural2-A',
  voice_provider TEXT DEFAULT 'elevenlabs' CHECK (voice_provider IN ('elevenlabs', 'azure', 'deepgram')),
  voice_speed DECIMAL(3, 2) DEFAULT 1.0,
  voice_pitch DECIMAL(4, 2) DEFAULT 1.0,
  interrupt_enabled BOOLEAN DEFAULT true,
  interrupt_threshold DECIMAL(3, 2) DEFAULT 0.8,
  language TEXT DEFAULT 'en-US',
  timezone TEXT,
  context_window_size INT DEFAULT 10,
  fallback_message TEXT,
  handoff_enabled BOOLEAN DEFAULT false,
  handoff_webhook_url TEXT,
  total_calls INT DEFAULT 0,
  avg_call_duration INT DEFAULT 0,
  success_rate DECIMAL(5, 2) DEFAULT 0,
  last_called_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  created_by UUID REFERENCES profiles(id)
);

CREATE TABLE phone_numbers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  agent_id UUID REFERENCES agents(id) ON DELETE SET NULL,
  phone_number TEXT NOT NULL,
  country_code TEXT NOT NULL,
  friendly_name TEXT,
  provider TEXT DEFAULT 'twilio',
  provider_id TEXT UNIQUE NOT NULL,
  inbound_enabled BOOLEAN DEFAULT true,
  outbound_enabled BOOLEAN DEFAULT true,
  sms_enabled BOOLEAN DEFAULT false,
  status TEXT DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'deleted')),
  purchased_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  inbound_calls INT DEFAULT 0,
  outbound_calls INT DEFAULT 0,
  last_call_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(workspace_id, phone_number)
);

CREATE TABLE calls (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id),
  agent_id UUID NOT NULL REFERENCES agents(id),
  phone_number_id UUID NOT NULL REFERENCES phone_numbers(id),
  caller_phone_number TEXT NOT NULL,
  caller_name TEXT,
  twilio_call_sid TEXT UNIQUE NOT NULL,
  direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
  status TEXT DEFAULT 'created' CHECK (status IN (
    'created', 'ringing', 'in_progress', 'completed', 
    'failed', 'no_answer', 'canceled', 'busy'
  )),
  started_at TIMESTAMPTZ,
  ended_at TIMESTAMPTZ,
  ringing_duration INT DEFAULT 0,
  actual_duration INT DEFAULT 0,
  success BOOLEAN,
  drop_reason TEXT,
  sentiment_score DECIMAL(3, 2),
  user_satisfaction DECIMAL(5, 2),
  transfer_requested BOOLEAN DEFAULT false,
  cost_cents INT DEFAULT 0,
  recording_storage_mb DECIMAL(10, 2),
  metadata JSONB DEFAULT '{}',
  context JSONB DEFAULT '{}',
  recording_consent BOOLEAN NOT NULL DEFAULT false,
  recording_url TEXT,
  recording_expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE call_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  call_id UUID NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
  content TEXT NOT NULL,
  audio_url TEXT,
  duration_ms INT,
  confidence DECIMAL(5, 4),
  sequence_number INT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL,
  ended_at TIMESTAMPTZ,
  token_count INT,
  model_used TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(call_id, sequence_number)
);

CREATE TABLE events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id),
  call_id UUID REFERENCES calls(id) ON DELETE SET NULL,
  type TEXT NOT NULL,
  severity TEXT DEFAULT 'info' CHECK (severity IN ('debug', 'info', 'warning', 'error', 'critical')),
  payload JSONB NOT NULL DEFAULT '{}',
  stack_trace TEXT,
  correlation_id TEXT UNIQUE,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE integrations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  api_key_encrypted TEXT,
  api_secret_encrypted TEXT,
  config JSONB DEFAULT '{}',
  status TEXT DEFAULT 'active',
  webhook_url TEXT,
  webhook_secret TEXT,
  events_subscribed TEXT[] DEFAULT ARRAY[]::TEXT[],
  rate_limit INT,
  rate_limit_window INT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  last_used_at TIMESTAMPTZ,
  UNIQUE(workspace_id, type)
);

-- RLS POLICIES (Simplified for initial setup)
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
ALTER TABLE phone_numbers ENABLE ROW LEVEL SECURITY;
ALTER TABLE calls ENABLE ROW LEVEL SECURITY;
ALTER TABLE call_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
ALTER TABLE integrations ENABLE ROW LEVEL SECURITY;
