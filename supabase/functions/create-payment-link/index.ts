// create-payment-link/index.ts  — Voice Pilot
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const RAZORPAY_KEY_ID        = Deno.env.get("RAZORPAY_KEY_ID");
const RAZORPAY_KEY_SECRET    = Deno.env.get("RAZORPAY_KEY_SECRET");
const SUPABASE_URL           = Deno.env.get("SUPABASE_URL");
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

const PRICING: Record<string, Record<number, number>> = {
  voice_pilot: { 1: 99900, 3: 89900, 6: 79900, 12: 69900 },
  all_in_one:  { 1: 499900, 3: 449900, 6: 399900, 12: 349900 },
};

function getPlanLabel(planId: string, interval: number): string {
  if (planId === "all_in_one") {
    if (interval === 1) return "GAP Core";
    if (interval === 3) return "GAP Pro";
    if (interval === 6) return "GAP Max";
    return "GAP Ultimate Ecosystem";
  }
  return "Voice Pilot";
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const { planId, interval = 1, userId, customerName, customerEmail, customerContact } = await req.json();

    if (!userId || !planId)      throw new Error("userId and planId are required");
    if (!PRICING[planId])        throw new Error(`Invalid planId: ${planId}`);

    const amount     = PRICING[planId][interval] ?? PRICING[planId][1];
    const planLabel  = getPlanLabel(planId, interval);
    const description = `${planLabel} Subscription (${interval} Month${interval > 1 ? "s" : ""})`;

    const supabase = createClient(SUPABASE_URL!, SUPABASE_SERVICE_ROLE_KEY!);

    const auth = btoa(`${RAZORPAY_KEY_ID}:${RAZORPAY_KEY_SECRET}`);
    const rzpRes = await fetch("https://api.razorpay.com/v1/payment_links", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": `Basic ${auth}` },
      body: JSON.stringify({
        amount,
        currency:        "INR",
        accept_partial:  false,
        description,
        customer: {
          name:    customerName || "Customer",
          email:   customerEmail,
          contact: customerContact,
        },
        notify:          { sms: false, email: true },
        reminder_enable: true,
        notes: { user_id: userId, plan: planId, interval: interval.toString(), product: "voice" },
        callback_url:    `${req.headers.get("origin") || "https://voice.getaipilot.in"}/dashboard/payment-success`,
        callback_method: "get",
      }),
    });

    const rzpData = await rzpRes.json();
    if (!rzpRes.ok) throw new Error(rzpData.error?.description || "Failed to create payment link");

    await supabase.from("payments").insert({
      user_id:                  userId,
      razorpay_payment_link_id: rzpData.id,
      plan:                     planLabel,
      plan_id:                  planId,
      amount,
      interval_months:          interval,
      status:                   "pending",
    }).then(({ error }) => { if (error) console.error("DB insert error:", error.message); });

    return new Response(
      JSON.stringify({ success: true, payment_link: rzpData.short_url }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );

  } catch (error: any) {
    console.error("[create-payment-link] Error:", error.message);
    return new Response(
      JSON.stringify({ success: false, error: error.message }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" }, status: 400 }
    );
  }
});
