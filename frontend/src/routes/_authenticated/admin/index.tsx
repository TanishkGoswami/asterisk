import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import {
  LayoutDashboard,
  Building2,
  Users,
  Bot,
  PhoneCall,
  Clock,
  DollarSign,
  Heart,
  TrendingDown,
  RefreshCw,
} from "lucide-react";
import { toast } from "sonner";

export const Route = createFileRoute("/_authenticated/admin/")({
  component: SuperAdminDashboard,
});

interface DashboardStats {
  total_workspaces: number;
  total_users: number;
  active_agents: number;
  active_calls: number;
  monthly_call_minutes: number;
  ai_cost_estimate_usd: number;
  sip_trunk_health: string;
  failed_calls: number;
}

interface ActiveCallChannel {
  channel: string;
  location: string;
  state: string;
  application: string;
  duration_seconds: number;
  stt_status: string;
  llm_latency_ms: number;
  tts_latency_ms: number;
}

function SuperAdminDashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [liveCalls, setLiveCalls] = useState<ActiveCallChannel[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchStatsAndCalls = async () => {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const headers = { 
        Authorization: `Bearer ${session.access_token}`,
        "ngrok-skip-browser-warning": "true"
      };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

      // 1. Fetch Summary Stats
      const statsRes = await fetch(`${apiUrl}/api/admin/dashboard/stats`, { headers });
      if (!statsRes.ok) throw new Error("Failed to load dashboard stats.");
      const statsData = await statsRes.json();
      setStats(statsData);

      // 2. Fetch Live Calls
      const callsRes = await fetch(`${apiUrl}/api/admin/live-calls`, { headers });
      if (callsRes.ok) {
        const callsData = await callsRes.json();
        setLiveCalls(callsData);
      }
    } catch (e: any) {
      toast.error(e.message || "Failed to retrieve stats.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatsAndCalls();
    // Poll active calls every 5 seconds
    const interval = setInterval(fetchStatsAndCalls, 5000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <p className="font-mono text-[12px] uppercase tracking-widest text-black/50">
          Loading platform metrics...
        </p>
      </div>
    );
  }

  const statCards = [
    { title: "Total Workspaces", value: stats?.total_workspaces ?? 0, icon: Building2, color: "bg-[#f7f7f5]" },
    { title: "Registered Users", value: stats?.total_users ?? 0, icon: Users, color: "bg-[#f7f7f5]" },
    { title: "Active Agents", value: stats?.active_agents ?? 0, icon: Bot, color: "bg-[#f7f7f5]" },
    { title: "Active Calls", value: stats?.active_calls ?? 0, icon: PhoneCall, color: "bg-[#dceeb1]" },
    { title: "Monthly Call Minutes", value: `${stats?.monthly_call_minutes ?? 0}m`, icon: Clock, color: "bg-[#f7f7f5]" },
    { title: "AI Cost (USD)", value: `$${stats?.ai_cost_estimate_usd ?? 0.0}`, icon: DollarSign, color: "bg-[#f7f7f5]" },
    { title: "SIP Trunk Status", value: stats?.sip_trunk_health ?? "0/0 Trunks", icon: Heart, color: "bg-[#c5b0f4]" },
    { title: "Failed Calls (Month)", value: stats?.failed_calls ?? 0, icon: TrendingDown, color: "bg-red-50" },
  ];

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-black/50">
            <LayoutDashboard className="h-3.5 w-3.5" />
            <span>Super Admin</span>
          </div>
          <h1 className="text-4xl font-[340] tracking-[-0.03em] text-black">Control Center</h1>
          <p className="max-w-2xl text-[14px] font-[320] leading-relaxed text-black/60">
            Platform monitoring and infrastructure control across all workspaces and Asterisk servers.
          </p>
        </div>
        <button
          onClick={fetchStatsAndCalls}
          className="flex h-10 w-10 items-center justify-center rounded-[12px] border border-[#e6e6e6] bg-white transition hover:bg-[#f7f7f5]"
        >
          <RefreshCw className="h-4 w-4 text-black/60" />
        </button>
      </div>

      {/* Stats Grid */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {statCards.map((card, idx) => (
          <div key={idx} className={`space-y-3 rounded-[20px] border border-[#e6e6e6] p-5 shadow-sm ${card.color}`}>
            <div className="flex items-center justify-between">
              <span className="font-mono text-[11px] uppercase tracking-widest text-black/50">{card.title}</span>
              <card.icon className="h-4 w-4 text-black opacity-30" />
            </div>
            <div>
              <div className="text-[28px] font-[450] text-black leading-none">{card.value}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Live Stream Call Monitor Section */}
      <div className="rounded-[20px] border border-[#e6e6e6] bg-white p-6 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <div className="space-y-1">
            <h3 className="text-[18px] font-[480] text-black tracking-tight flex items-center gap-2">
              <span>Realtime Call Monitor</span>
              {liveCalls.length > 0 && (
                <span className="flex h-2.5 w-2.5 rounded-full bg-[#1ea64a] animate-pulse" />
              )}
            </h3>
            <p className="text-[13px] text-black/60 font-[320]">
              Active conversation loops running right now on Asterisk.
            </p>
          </div>
          <span className="font-mono text-[11px] text-black/40">
            {liveCalls.length} Active
          </span>
        </div>

        {liveCalls.length === 0 ? (
          <div className="flex h-[200px] flex-col items-center justify-center rounded-[14px] border border-dashed border-[#e6e6e6] bg-[#fcfcfb]">
            <PhoneCall className="h-8 w-8 text-black/10 mb-2" />
            <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-black/40">
              No live connections active
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-[13px]">
              <thead>
                <tr className="border-b border-[#e6e6e6] text-black/40 font-mono text-[11px]">
                  <th className="py-2.5">Channel</th>
                  <th className="py-2.5">State</th>
                  <th className="py-2.5">Application</th>
                  <th className="py-2.5">STT</th>
                  <th className="py-2.5">LLM Latency</th>
                  <th className="py-2.5">TTS Latency</th>
                </tr>
              </thead>
              <tbody>
                {liveCalls.map((call, idx) => (
                  <tr key={idx} className="border-b border-[#e6e6e6] hover:bg-[#fcfcfb]">
                    <td className="py-3 font-mono font-medium text-black">{call.channel}</td>
                    <td className="py-3">
                      <span className="rounded-full bg-green-50 px-2 py-0.5 text-[11px] font-medium text-green-700">
                        {call.state}
                      </span>
                    </td>
                    <td className="py-3 text-black/70">{call.application}</td>
                    <td className="py-3 text-black/70 font-mono">{call.stt_status}</td>
                    <td className="py-3 font-mono text-black/60">{call.llm_latency_ms}ms</td>
                    <td className="py-3 font-mono text-black/60">{call.tts_latency_ms}ms</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
