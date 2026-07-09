// sync-from-hub/index.ts  — Voice Pilot
// Called by hub (getaipilot.in) when user purchases GAP Ultimate Ecosystem or Voice-related plan
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL              = Deno.env.get("SUPABASE_URL");
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
const VOICE_SYNC_SECRET         = Deno.env.get("VOICE_SYNC_SECRET");

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type, x-sync-secret",
};

function plansIncludesVoice(planId: string): boolean {
  const p = planId.toLowerCase();
  return p.includes("all_in_one") || p.includes("voice") || p.includes("calling");
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  // Validate sync secret
  const secret = req.headers.get("x-sync-secret");
  if (VOICE_SYNC_SECRET && secret !== VOICE_SYNC_SECRET) {
    return new Response(JSON.stringify({ error: "Unauthorized" }), { status: 401, headers: corsHeaders });
  }

  try {
    const { email, plan_id, plan_label, expires_at, hub_user_id } = await req.json();
    if (!email || !plan_id) throw new Error("email and plan_id are required");

    // Only sync plans that include Voice access
    if (!plansIncludesVoice(plan_id)) {
      return new Response(JSON.stringify({ skipped: true, reason: "plan does not include voice access" }), {
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      });
    }

    let resolvedPlan = plan_label;
    if (!resolvedPlan && plan_id) {
      const p = plan_id.toLowerCase();
      if (p.includes("monthly") || p.includes("core") || p === "all_in_one_bundle_monthly") resolvedPlan = "GAP Core";
      else if (p.includes("quarterly") || p.includes("pro") || p === "all_in_one_bundle_quarterly") resolvedPlan = "GAP Pro";
      else if (p.includes("half_yearly") || p.includes("max") || p === "all_in_one_bundle_half_yearly") resolvedPlan = "GAP Max";
    }
    if (!resolvedPlan) {
      resolvedPlan = "GAP Ultimate Ecosystem";
    }
    const supabase = createClient(SUPABASE_URL!, SUPABASE_SERVICE_ROLE_KEY!);

    await supabase.from("hub_subscriptions").upsert(
      {
        email,
        hub_user_id:         hub_user_id || null,
        plan:                resolvedPlan,
        plan_id,
        subscription_status: "active",
        expires_at:          expires_at || null,
        synced_at:           new Date().toISOString(),
        updated_at:          new Date().toISOString(),
      },
      { onConflict: "email" }
    );

    console.log(`[sync-from-hub] ✅ ${email} → ${resolvedPlan}`);

    return new Response(JSON.stringify({ success: true }), {
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });

  } catch (error: any) {
    console.error("[sync-from-hub] Error:", error.message);
    return new Response(JSON.stringify({ success: false, error: error.message }), {
      headers: { ...corsHeaders, "Content-Type": "application/json" }, status: 400,
    });
  }
});
