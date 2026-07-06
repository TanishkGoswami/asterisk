import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Activity, Loader2, Phone, PhoneCall, PhoneOff, Clock, Calendar, ShieldAlert } from "lucide-react";
import { useWorkspace } from "@/context/WorkspaceContext";
import { toast } from "sonner";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  BarChart,
  Bar,
} from "recharts";

export const Route = createFileRoute("/_authenticated/dashboard/analytics")({
  component: AnalyticsPage,
});

interface CallRecord {
  id: string;
  status: string;
  duration: number; // in seconds
  created_at: string;
  agent_id: string;
}

interface AgentRecord {
  id: string;
  name: string;
}

function AnalyticsPage() {
  const { workspaceId, authHeaders, loading: contextLoading } = useWorkspace();
  const [loading, setLoading] = useState(true);
  const [calls, setCalls] = useState<CallRecord[]>([]);
  const [agentMap, setAgentMap] = useState<Record<string, string>>({});

  const apiUrl = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

  useEffect(() => {
    if (contextLoading) return;
    if (!workspaceId || !authHeaders) {
      setLoading(false);
      return;
    }

    async function fetchAnalyticsData() {
      try {
        const [callsRes, agentsRes] = await Promise.all([
          fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/calls`, { headers: authHeaders || undefined }),
          fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/agents`, { headers: authHeaders || undefined }),
        ]);

        if (callsRes.ok) {
          const callsData = await callsRes.json();
          setCalls(callsData);
        } else {
          toast.error("Failed to load call logs for analytics");
        }

        if (agentsRes.ok) {
          const agentsData = await agentsRes.json();
          const lookup: Record<string, string> = {};
          agentsData.forEach((a: AgentRecord) => {
            lookup[a.id] = a.name;
          });
          setAgentMap(lookup);
        }
      } catch (err) {
        console.error("Error loading analytics:", err);
      } finally {
        setLoading(false);
      }
    }

    fetchAnalyticsData();
  }, [workspaceId, authHeaders, contextLoading, apiUrl]);

  if (loading) {
    return (
      <div className="flex h-80 flex-col items-center justify-center space-y-4">
        <Loader2 className="h-10 w-10 animate-spin text-black opacity-20" />
        <p className="font-mono text-[12px] uppercase tracking-[0.2em] opacity-40">Loading workspace analytics...</p>
      </div>
    );
  }

  // Calculate Metrics
  const totalCalls = calls.length;
  const successfulCalls = calls.filter(c => c.status === "completed" || c.status === "answered" || c.status === "ringing").length;
  const failedCalls = calls.filter(c => c.status === "failed" || c.status === "no-answer").length;
  
  const totalDurationSeconds = calls.reduce((acc, curr) => acc + (curr.duration || 0), 0);
  const totalMinutes = Math.round(totalDurationSeconds / 60);
  const avgDurationSeconds = totalCalls > 0 ? Math.round(totalDurationSeconds / totalCalls) : 0;
  
  const formatDuration = (sec: number) => {
    const mins = Math.floor(sec / 60);
    const secs = sec % 60;
    return `${mins}m ${secs}s`;
  };

  // Group by Date for AreaChart (Daily Call Volume)
  const dailyGroups: Record<string, number> = {};
  // Initialize last 7 days to ensure chart has points even if data is sparse
  for (let i = 6; i >= 0; i--) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    const dateStr = d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    dailyGroups[dateStr] = 0;
  }

  calls.forEach(c => {
    const date = new Date(c.created_at);
    const dateStr = date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    // Update count only if it falls in the current 7 days range
    if (dailyGroups[dateStr] !== undefined) {
      dailyGroups[dateStr] += 1;
    } else {
      dailyGroups[dateStr] = 1;
    }
  });

  const dailyVolumeData = Object.entries(dailyGroups).map(([day, count]) => ({
    day,
    calls: count
  }));

  // Group by Agent for BarChart
  const agentGroups: Record<string, number> = {};
  calls.forEach(c => {
    const name = agentMap[c.agent_id] || `Agent (${c.agent_id.substring(0, 8)})`;
    agentGroups[name] = (agentGroups[name] || 0) + 1;
  });

  const agentVolumeData = Object.entries(agentGroups).map(([agent, count]) => ({
    agent,
    calls: count
  }));

  if (totalCalls === 0) {
    return (
      <div className="mx-auto flex max-w-7xl flex-col gap-8 px-4 py-3 md:px-5 md:py-4">
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-[#999999]">
            <Activity className="h-3.5 w-3.5" />
            <span>Telemetry Insights</span>
          </div>
          <h1 className="text-4xl font-[340] tracking-[-0.03em] text-black md:text-5xl">Analytics</h1>
        </div>
        <div className="flex flex-col items-center justify-center border border-[#e6e6e6] bg-white rounded-[24px] p-20 text-center shadow-sm">
          <ShieldAlert className="h-10 w-10 text-black/10 mb-4" />
          <h3 className="text-[16px] font-[480] text-black">No Call Telemetry Found</h3>
          <p className="text-[13px] text-black/60 font-[320] leading-relaxed max-w-sm mt-1">
            Initiate test calls or receive inbound calls to populate real-time metrics and volume visualization.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-8 px-4 py-3 md:px-5 md:py-4">
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-[#999999]">
          <Activity className="h-3.5 w-3.5" />
          <span>Telemetry Insights</span>
        </div>
        <h1 className="text-4xl font-[340] tracking-[-0.03em] text-black md:text-5xl">Analytics</h1>
        <p className="text-[#666666] text-[18px] max-w-2xl font-[320] leading-relaxed">
          Monitor your conversational engines, connection statistics, and calling volumes.
        </p>
      </div>

      {/* Stats Grid */}
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
        <div className="space-y-1.5 rounded-[20px] border border-[#e6e6e6] bg-white p-6 shadow-sm">
          <div className="flex justify-between items-start">
            <p className="font-mono text-[10px] uppercase tracking-wider text-[#999999]">Total Calls</p>
            <Phone className="h-4 w-4 text-black opacity-30" />
          </div>
          <div className="text-[32px] font-[450] text-black">{totalCalls}</div>
        </div>
        <div className="space-y-1.5 rounded-[20px] border border-[#e6e6e6] bg-white p-6 shadow-sm">
          <div className="flex justify-between items-start">
            <p className="font-mono text-[10px] uppercase tracking-wider text-[#999999]">Successful</p>
            <PhoneCall className="h-4 w-4 text-[#1ea64a] opacity-60" />
          </div>
          <div className="text-[32px] font-[450] text-black">{successfulCalls}</div>
        </div>
        <div className="space-y-1.5 rounded-[20px] border border-[#e6e6e6] bg-white p-6 shadow-sm">
          <div className="flex justify-between items-start">
            <p className="font-mono text-[10px] uppercase tracking-wider text-[#999999]">Failed / Missed</p>
            <PhoneOff className="h-4 w-4 text-[#ff3d8b] opacity-60" />
          </div>
          <div className="text-[32px] font-[450] text-black">{failedCalls}</div>
        </div>
        <div className="space-y-1.5 rounded-[20px] border border-[#e6e6e6] bg-white p-6 shadow-sm">
          <div className="flex justify-between items-start">
            <p className="font-mono text-[10px] uppercase tracking-wider text-[#999999]">Avg Duration</p>
            <Clock className="h-4 w-4 text-black opacity-30" />
          </div>
          <div className="text-[32px] font-[450] text-black">{formatDuration(avgDurationSeconds)}</div>
        </div>
      </div>

      <div className="grid gap-8 md:grid-cols-2">
        {/* Daily Call Volume */}
        <div className="bg-white border border-[#e6e6e6] rounded-[24px] overflow-hidden flex flex-col shadow-sm">
          <div className="p-6 border-b border-[#f1f1f1] flex items-center gap-2">
            <Calendar className="h-4 w-4 text-black opacity-60" />
            <h3 className="text-[16px] font-[480] text-black">Daily Call Volume</h3>
          </div>
          <div className="h-[250px] w-full p-6">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={dailyVolumeData}>
                <defs>
                  <linearGradient id="callGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#c5b0f4" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#c5b0f4" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="day" stroke="#999999" fontSize={11} tickLine={false} axisLine={false} dy={5} />
                <YAxis stroke="#999999" fontSize={11} tickLine={false} axisLine={false} />
                <Tooltip contentStyle={{ backgroundColor: "white", border: "1px solid #e6e6e6", borderRadius: "12px", fontSize: "12px" }} />
                <Area type="monotone" dataKey="calls" stroke="#c5b0f4" fillOpacity={1} fill="url(#callGradient)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Agent Volume */}
        <div className="bg-white border border-[#e6e6e6] rounded-[24px] overflow-hidden flex flex-col shadow-sm">
          <div className="p-6 border-b border-[#f1f1f1] flex items-center gap-2">
            <Activity className="h-4 w-4 text-black opacity-60" />
            <h3 className="text-[16px] font-[480] text-black">Calls per Agent</h3>
          </div>
          <div className="h-[250px] w-full p-6">
            {agentVolumeData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={agentVolumeData}>
                  <XAxis dataKey="agent" stroke="#999999" fontSize={11} tickLine={false} axisLine={false} dy={5} />
                  <YAxis stroke="#999999" fontSize={11} tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={{ backgroundColor: "white", border: "1px solid #e6e6e6", borderRadius: "12px", fontSize: "12px" }} />
                  <Bar dataKey="calls" fill="#f4ecd6" radius={[4, 4, 0, 0]} maxBarSize={40} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-full items-center justify-center text-[13px] text-[#999999] italic">
                No agent data logged yet
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
