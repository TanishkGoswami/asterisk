// verify-subscription/index.ts  — Voice Pilot
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const RAZORPAY_KEY_ID           = Deno.env.get("RAZORPAY_KEY_ID");
const RAZORPAY_KEY_SECRET       = Deno.env.get("RAZORPAY_KEY_SECRET");
const SUPABASE_URL              = Deno.env.get("SUPABASE_URL");
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
// Optional: push plan to hub's hub_subscriptions after payment
const HUB_SUPABASE_URL          = Deno.env.get("HUB_SUPABASE_URL");
const HUB_SERVICE_ROLE_KEY      = Deno.env.get("HUB_SERVICE_ROLE_KEY");

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

function getPlanName(planId: string): string {
  if (!planId) return "Voice Pilot";
  const p = planId.toLowerCase();
  if (p.includes("all_in_one_bundle_monthly")) return "GAP Core";
  if (p.includes("all_in_one_bundle_quarterly")) return "GAP Pro";
  if (p.includes("all_in_one_bundle_half_yearly")) return "GAP Max";
  if (p.includes("all_in_one") || p.includes("ultimate")) return "GAP Ultimate Ecosystem";
  return "Voice Pilot";
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const { razorpayPaymentLinkId } = await req.json();
    if (!razorpayPaymentLinkId) throw new Error("razorpayPaymentLinkId is required");

    const auth   = btoa(`${RAZORPAY_KEY_ID}:${RAZORPAY_KEY_SECRET}`);
    const rzpRes = await fetch(
      `https://api.razorpay.com/v1/payment_links/${razorpayPaymentLinkId}`,
      { headers: { "Authorization": `Basic ${auth}` } }
    );
    const rzpData = await rzpRes.json();
    if (!rzpRes.ok) throw new Error(rzpData.error?.description || "Failed to fetch Razorpay status");

    const status = rzpData.status;
    const userId = rzpData.notes?.user_id;
    const planId = rzpData.notes?.plan;

    const supabase = createClient(SUPABASE_URL!, SUPABASE_SERVICE_ROLE_KEY!);

    // Update payments table
    await supabase.from("payments").update({ status }).eq("razorpay_payment_link_id", razorpayPaymentLinkId);

    if (status === "paid" && userId && planId) {
      const planName = getPlanName(planId);

      // Update auth user_metadata
      const { error: authErr } = await supabase.auth.admin.updateUserById(userId, {
        user_metadata: { plan: planName, subscription_status: "active" },
      });
      if (authErr) throw new Error("Payment verified but failed to update user. Contact support.");

      // Get user email
      const { data: authUser } = await supabase.auth.admin.getUserById(userId);
      const email = authUser?.user?.email;

      // Upsert local hub_subscriptions
      if (email) {
        await supabase.from("hub_subscriptions").upsert(
          { email, plan: planName, plan_id: planId, subscription_status: "active", updated_at: new Date().toISOString(), synced_at: new Date().toISOString() },
          { onConflict: "email" }
        );

        // Also push to hub's hub_subscriptions (getaipilot.in) if configured
        if (HUB_SUPABASE_URL && HUB_SERVICE_ROLE_KEY) {
          const hub = createClient(HUB_SUPABASE_URL, HUB_SERVICE_ROLE_KEY);
          await hub.from("hub_subscriptions").upsert(
            { email, plan: planName, plan_id: planId, subscription_status: "active", updated_at: new Date().toISOString(), synced_at: new Date().toISOString() },
            { onConflict: "email" }
          );
          console.log(`[verify-subscription] ✅ Pushed to hub: ${email} → ${planName}`);
        }
      }

      console.log(`[verify-subscription] ✅ ${userId} → ${planName}`);

      return new Response(
        JSON.stringify({ success: true, status, plan: planName }),
        { headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    return new Response(
      JSON.stringify({ success: true, status }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );

  } catch (error: any) {
    console.error("[verify-subscription] Error:", error.message);
    return new Response(
      JSON.stringify({ success: false, error: error.message }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" }, status: 400 }
    );
  }
});
