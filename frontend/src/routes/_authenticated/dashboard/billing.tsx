import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Receipt, Loader2, Info } from "lucide-react";
import { useWorkspace } from "@/context/WorkspaceContext";
import { toast } from "sonner";

export const Route = createFileRoute("/_authenticated/dashboard/billing")({
  component: BillingPage,
});

interface BillingData {
  plan_name: string;
  monthly_minute_limit: number;
  used_minutes: number;
  remaining_minutes: number;
  billing_status: string;
  estimated_cost: number;
  concurrency_limit: number;
}

function BillingPage() {
  const { workspaceId, authHeaders, loading: contextLoading } = useWorkspace();
  const [loading, setLoading] = useState(true);
  const [billing, setBilling] = useState<BillingData | null>(null);

  const apiUrl = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

  useEffect(() => {
    if (contextLoading) return;
    if (!workspaceId || !authHeaders) {
      setLoading(false);
      return;
    }

    async function fetchBilling() {
      try {
        const res = await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/billing`, { headers: authHeaders || undefined });
        if (res.ok) {
          const data = await res.json();
          setBilling(data);
        } else {
          toast.error("Failed to load billing metrics");
        }
      } catch (err) {
        console.error("Error fetching billing:", err);
      } finally {
        setLoading(false);
      }
    }

    fetchBilling();
  }, [workspaceId, authHeaders, contextLoading, apiUrl]);

  if (loading) {
    return (
      <div className="flex h-80 flex-col items-center justify-center space-y-4">
        <Loader2 className="h-10 w-10 animate-spin text-black opacity-20" />
        <p className="font-mono text-[12px] uppercase tracking-[0.2em] opacity-40">Loading billing metrics...</p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-8 px-4 py-3 md:px-5 md:py-4">
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-[#999999]">
          <Receipt className="h-3.5 w-3.5" />
          <span>Financial Operations</span>
        </div>
        <h1 className="text-4xl font-[340] tracking-[-0.03em] text-black md:text-5xl">Billing</h1>
        <p className="text-[#666666] text-[18px] max-w-2xl font-[320] leading-relaxed">
          Manage your subscription plans, telemetry consumption, and payment methods.
        </p>
      </div>

      <div className="grid gap-8 md:grid-cols-3">
        <div className="md:col-span-2 bg-white border border-[#e6e6e6] rounded-[24px] overflow-hidden flex flex-col shadow-sm">
          <div className="p-8 bg-[#c5b0f4] text-black border-b border-black/5">
            <h3 className="text-[20px] font-[480]">Telemetry Consumption</h3>
            <p className="text-[14px] text-black/60 font-[320]">Voice synthesis and processing minutes for current cycle.</p>
          </div>
          
          <div className="p-8 space-y-6">
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
              <div className="p-6 rounded-[20px] bg-[#f7f7f5] border border-[#e6e6e6]">
                <span className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">Used Minutes</span>
                <p className="text-[32px] font-[450] text-black mt-1">
                  {billing ? billing.used_minutes : 0}
                </p>
              </div>
              <div className="p-6 rounded-[20px] bg-[#f7f7f5] border border-[#e6e6e6]">
                <span className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">Monthly Limit</span>
                <p className="text-[32px] font-[450] text-black mt-1">
                  {billing ? billing.monthly_minute_limit : 1000}
                </p>
              </div>
              <div className="p-6 rounded-[20px] bg-[#f7f7f5] border border-[#e6e6e6]">
                <span className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">Remaining</span>
                <p className="text-[32px] font-[450] text-black mt-1">
                  {billing ? billing.remaining_minutes : 1000}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="p-6 rounded-[20px] bg-[#f7f7f5] border border-[#e6e6e6]">
                <span className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">Current Accrual</span>
                <p className="text-[28px] font-[450] text-black mt-1">
                  ${billing ? billing.estimated_cost.toFixed(2) : "0.00"}
                </p>
              </div>
              <div className="p-6 rounded-[20px] bg-[#f7f7f5] border border-[#e6e6e6]">
                <span className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">Concurrency limit</span>
                <p className="text-[28px] font-[450] text-black mt-1">
                  {billing ? billing.concurrency_limit : 1} {billing && billing.concurrency_limit === 1 ? "Channel" : "Channels"}
                </p>
              </div>
            </div>
          </div>
        </div>

        <div className="bg-white border border-[#e6e6e6] rounded-[24px] p-8 space-y-8 shadow-sm">
          <div className="space-y-1">
            <h3 className="text-[18px] font-[480] text-black">Financial Source</h3>
            <p className="text-[13px] text-[#666666] font-[320]">Primary settlement method.</p>
          </div>
          <div className="space-y-6">
            <div className="flex items-center gap-4 p-4 rounded-[16px] border border-[#e6e6e6] bg-[#f7f7f5]/30">
              <p className="text-[13px] text-[#999999] italic font-[320]">No payment source connected.</p>
            </div>
            <Button 
              disabled
              className="w-full h-11 rounded-full bg-[#f7f7f5] text-[#999999] hover:bg-[#f7f7f5] text-[13px] font-[480] cursor-not-allowed border border-[#e6e6e6]"
            >
              Update Payment Method (Coming Soon)
            </Button>
            <div className="h-px w-full bg-[#f1f1f1]" />
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-[13px] text-[#999999] font-[320]">Active Plan</span>
                <span className="text-[13px] font-[480] text-black capitalize">
                  {billing ? billing.plan_name : "Free Tier"}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-[13px] text-[#999999] font-[320]">Engine Cost</span>
                <span className="text-[13px] font-[480] text-black">$0.06/min</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-[13px] text-[#999999] font-[320]">Status</span>
                <span className={`text-[12px] font-mono uppercase tracking-wider px-2 py-0.5 rounded-sm ${
                  billing && billing.billing_status === "active" ? "bg-[#dceeb1] text-[#1ea64a]" : "bg-[#f7f7f5] text-[#999999]"
                }`}>
                  {billing ? billing.billing_status : "active"}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="bg-white border border-[#e6e6e6] rounded-[24px] overflow-hidden shadow-sm">
        <div className="p-8 border-b border-[#f1f1f1] flex items-center gap-3">
          <Receipt className="h-5 w-5 text-black opacity-60" />
          <h3 className="text-[20px] font-[480] text-black">Ledger History</h3>
        </div>
        <div className="p-4">
          <div className="divide-y divide-[#f1f1f1] flex items-center justify-center p-8 gap-2 text-[#999999]">
            <Info className="h-4 w-4" />
            <p className="text-center text-[13px] font-[320] italic">Invoice ledger history is coming soon.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
