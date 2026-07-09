-- Migration: Add sso_nonces table for SSO login replay prevention
CREATE TABLE IF NOT EXISTS public.sso_nonces (
    jti UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Enable Row Level Security (RLS)
ALTER TABLE public.sso_nonces ENABLE ROW LEVEL SECURITY;

-- Allow service_role full access (used by the python backend with service role client)
CREATE POLICY "Allow service role full access" ON public.sso_nonces
    FOR ALL TO service_role USING (true) WITH CHECK (true);
