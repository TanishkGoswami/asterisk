-- Migration: 016_admin_production_safety.sql
-- Description: Adds tables for administrative audit logs, Asterisk configurations history, provider health telemetry, and campaigns queue metrics.

-- 1. Create admin_audit_logs if missing
CREATE TABLE IF NOT EXISTS admin_audit_logs (
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

CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_user_date ON admin_audit_logs (admin_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_action_date ON admin_audit_logs (action, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_target ON admin_audit_logs (target_type, target_id);

-- 2. Create asterisk_config_versions if missing
CREATE TABLE IF NOT EXISTS asterisk_config_versions (
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

CREATE INDEX IF NOT EXISTS idx_asterisk_config_versions_num ON asterisk_config_versions (version_number);
CREATE INDEX IF NOT EXISTS idx_asterisk_config_versions_active ON asterisk_config_versions (is_active);
CREATE INDEX IF NOT EXISTS idx_asterisk_config_versions_date ON asterisk_config_versions (created_at DESC);

-- 3. Create provider_health_events if missing
CREATE TABLE IF NOT EXISTS provider_health_events (
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

CREATE INDEX IF NOT EXISTS idx_provider_health_prov ON provider_health_events (provider, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_provider_health_srv ON provider_health_events (service_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_provider_health_stat ON provider_health_events (status, created_at DESC);

-- 4. Create batch_call_runs if missing
CREATE TABLE IF NOT EXISTS batch_call_runs (
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
CREATE TABLE IF NOT EXISTS batch_call_items (
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

CREATE INDEX IF NOT EXISTS idx_batch_call_items_run ON batch_call_items (batch_run_id);
CREATE INDEX IF NOT EXISTS idx_batch_call_items_workspace ON batch_call_items (workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_batch_call_items_status ON batch_call_items (status);

-- 6. Add tracking columns to existing tables
ALTER TABLE sip_trunk_providers 
ADD COLUMN IF NOT EXISTS created_by uuid,
ADD COLUMN IF NOT EXISTS updated_by uuid;

ALTER TABLE did_numbers 
ADD COLUMN IF NOT EXISTS created_by uuid,
ADD COLUMN IF NOT EXISTS updated_by uuid;

ALTER TABLE workspace_limits 
ADD COLUMN IF NOT EXISTS updated_by uuid;
