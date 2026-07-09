/**
 * voice-sso-verify (RECEIVER) — voice pilot supabase project
 *
 * Self-contained — no external file imports. Works via Supabase Dashboard or CLI.
 *
 * Called by the /voice-sso frontend page with the token issued by
 * getaipilot.in's `voice-sso` edge function.
 *
 * Verifies the HMAC-SHA256 signature, prevents replay via sso_nonces table,
 * then generates a Supabase magic-link so the browser can establish a real
 * auth session without sharing cross-project secrets.
 *
 * Required env vars:
 *   VOICE_PILOT_SSO_SECRET   — shared secret (same value as hub)
 *   SUPABASE_URL             — auto-set by Supabase
 *   SUPABASE_SERVICE_ROLE_KEY — auto-set by Supabase
 *   CLIENT_URL               — e.g. https://voice.getaipilot.online
 */

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization',
};

function jsonRes(status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...corsHeaders },
  });
}

const toBase64Url = (s: string): string =>
  btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

async function hmacSign(message: string, secret: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(message));
  return toBase64Url(String.fromCharCode(...new Uint8Array(sig)));
}

function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  const bufA = new TextEncoder().encode(a);
  const bufB = new TextEncoder().encode(b);
  let diff = 0;
  for (let i = 0; i < bufA.length; i++) diff |= bufA[i] ^ bufB[i];
  return diff === 0;
}

function decodePayload(encoded: string): Record<string, unknown> | null {
  try {
    let b64 = encoded.replace(/-/g, '+').replace(/_/g, '/');
    const padding = b64.length % 4;
    if (padding) b64 += '='.repeat(4 - padding);
    return JSON.parse(atob(b64));
  } catch {
    return null;
  }
}

Deno.serve(async (req: Request) => {
  if (req.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: corsHeaders });
  }
  if (req.method !== 'POST') {
    return jsonRes(405, { error: 'Method not allowed' });
  }

  const supabaseUrl  = Deno.env.get('SUPABASE_URL') ?? '';
  const supabaseKey  = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? '';
  const ssoSecret    = Deno.env.get('VOICE_PILOT_SSO_SECRET') ?? '';
  const clientUrl    = (Deno.env.get('CLIENT_URL') || 'https://voice.getaipilot.online').replace(/\/$/, '');

  if (!supabaseUrl || !supabaseKey) {
    return jsonRes(500, { error: 'Server misconfiguration: missing Supabase credentials' });
  }
  if (!ssoSecret) {
    console.error('[voice-sso-verify] Missing VOICE_PILOT_SSO_SECRET');
    return jsonRes(503, { error: 'SSO not configured on this server' });
  }

  let body: Record<string, unknown> = {};
  try {
    body = await req.json();
  } catch {
    return jsonRes(400, { error: 'Invalid JSON body' });
  }

  const token = body?.token;
  if (!token || typeof token !== 'string') {
    return jsonRes(400, { error: 'Missing SSO token' });
  }

  // ── Split at last dot: "<encoded>.<signature>" ──────────────────────────
  const lastDot = token.lastIndexOf('.');
  if (lastDot < 1 || lastDot === token.length - 1) {
    return jsonRes(400, { error: 'Malformed SSO token' });
  }
  const encoded   = token.slice(0, lastDot);
  const signature = token.slice(lastDot + 1);

  // ── Verify HMAC ──────────────────────────────────────────────────────────
  const expected = await hmacSign(encoded, ssoSecret);
  if (!constantTimeEqual(signature, expected)) {
    console.warn('[voice-sso-verify] Signature mismatch — rejected');
    return jsonRes(401, { error: 'Invalid SSO token' });
  }

  // ── Decode and validate claims ───────────────────────────────────────────
  const payload = decodePayload(encoded);
  if (!payload) {
    return jsonRes(400, { error: 'Unreadable SSO payload' });
  }

  const { email, aud, iss, exp, jti } = payload as Record<string, unknown>;

  if (aud !== 'voicepilot') {
    return jsonRes(401, { error: 'Invalid token audience' });
  }
  if (iss !== 'getaipilot.in') {
    return jsonRes(401, { error: 'Invalid token issuer' });
  }
  if (!email || typeof email !== 'string') {
    return jsonRes(400, { error: 'Token missing email' });
  }
  if (!jti || typeof jti !== 'string') {
    return jsonRes(400, { error: 'Token missing nonce' });
  }
  if (typeof exp !== 'number' || Date.now() > exp) {
    return jsonRes(401, { error: 'SSO token has expired' });
  }

  const supabase = createClient(supabaseUrl, supabaseKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });

  // ── Replay prevention: insert JTI ────────────────────────────────────────
  const { error: nonceError } = await supabase
    .from('sso_nonces')
    .insert({ jti, email, expires_at: new Date(exp as number).toISOString() });

  if (nonceError) {
    if (nonceError.code === '23505') {
      console.warn(`[voice-sso-verify] Replay detected jti=${jti}`);
      return jsonRes(401, { error: 'SSO token already used' });
    }
    console.error('[voice-sso-verify] Nonce insert error:', nonceError.message);
    return jsonRes(500, { error: 'Nonce check failed' });
  }

  // ── Generate magic-link ───────────────────────────────────────────────────
  const redirectTo = `${clientUrl}/auth/callback`;

  const { data: linkData, error: linkError } = await supabase.auth.admin.generateLink({
    type: 'magiclink',
    email,
    options: { redirectTo },
  });

  if (linkError || !linkData?.properties?.action_link) {
    console.error('[voice-sso-verify] generateLink error:', linkError?.message);
    return jsonRes(500, { error: 'Failed to generate login link' });
  }

  console.log(`[voice-sso-verify] Magic link issued for ${email}`);
  return jsonRes(200, { magic_link_url: linkData.properties.action_link });
});
