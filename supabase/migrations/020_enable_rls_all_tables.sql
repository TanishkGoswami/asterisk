-- Migration 020: Enable Row Level Security (RLS) and define access policies for flagged public tables

-- 1. Enable RLS on all flagged tables
ALTER TABLE public.outbound_safety_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.call_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sso_nonces ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.asterisk_config_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.batch_call_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.provider_health_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.call_reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_contexts ENABLE ROW LEVEL SECURITY;

-- 2. Define Policies for Backend-Only Tables (service_role full access)
-- Note: Supabase service_role key bypasses RLS by default, but defining these explicitly guarantees safe access.

-- outbound_safety_events
DROP POLICY IF EXISTS "Allow service role full access" ON public.outbound_safety_events;
CREATE POLICY "Allow service role full access" ON public.outbound_safety_events
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- call_usage
DROP POLICY IF EXISTS "Allow service role full access" ON public.call_usage;
CREATE POLICY "Allow service role full access" ON public.call_usage
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- sso_nonces
DROP POLICY IF EXISTS "Allow service role full access" ON public.sso_nonces;
CREATE POLICY "Allow service role full access" ON public.sso_nonces
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- asterisk_config_versions
DROP POLICY IF EXISTS "Allow service role full access" ON public.asterisk_config_versions;
CREATE POLICY "Allow service role full access" ON public.asterisk_config_versions
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- batch_call_items
DROP POLICY IF EXISTS "Allow service role full access" ON public.batch_call_items;
CREATE POLICY "Allow service role full access" ON public.batch_call_items
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- provider_health_events
DROP POLICY IF EXISTS "Allow service role full access" ON public.provider_health_events;
CREATE POLICY "Allow service role full access" ON public.provider_health_events
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- call_reservations
DROP POLICY IF EXISTS "Allow service role full access" ON public.call_reservations;
CREATE POLICY "Allow service role full access" ON public.call_reservations
    FOR ALL TO service_role USING (true) WITH CHECK (true);


-- 3. Define Policies for Frontend/Backend Accessed Table (agent_contexts)
-- Allow authenticated users (frontend client) full read/write management access to agent_contexts
DROP POLICY IF EXISTS "Allow authenticated users to manage agent_contexts" ON public.agent_contexts;
CREATE POLICY "Allow authenticated users to manage agent_contexts" ON public.agent_contexts
    FOR ALL TO authenticated USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow service role full access" ON public.agent_contexts;
CREATE POLICY "Allow service role full access" ON public.agent_contexts
    FOR ALL TO service_role USING (true) WITH CHECK (true);


-- 4. Reload PostgREST schema cache
NOTIFY pgrst, 'reload schema';
