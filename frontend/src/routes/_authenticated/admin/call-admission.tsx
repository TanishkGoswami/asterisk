import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { Activity, ShieldAlert, CheckCircle, AlertTriangle, RefreshCw, Layers, ShieldX } from "lucide-react";
import { toast } from "sonner";

export const Route = createFileRoute("/_authenticated/admin/call-admission")({
  component: CallAdmissionManager,
});

interface ActiveCounters {
  workspace_active_calls: Record<string, number>;
  agent_active_calls: Record<string, number>;
  trunk_active_calls: Record<string, number>;
}

interface LimitEvent {
  id: string;
  workspace_id: string;
  call_uuid: string;
  direction: string;
  limit_type: string;
  limit_value: number;
  current_value: number;
  rejection_reason: string;
  created_at: string;
}

interface Workspace {
  id: string;
  name: string;
}

function CallAdmissionManager() {
  const [counters, setCounters] = useState<ActiveCounters | null>(null);
  const [events, setEvents] = useState<LimitEvent[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [reconciling, setReconciling] = useState(false);
  const [page, setPage] = useState(1);
  const [totalEvents, setTotalEvents] = useState<LimitEvent[]>([]);

  const fetchCACData = async () => {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const headers = { Authorization: `Bearer ${session.access_token}` };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

      // 1. Fetch active Redis counters
      const countersRes = await fetch(`${apiUrl}/api/admin/billing/active-counters`, { headers });
      if (countersRes.ok) {
        const countersData = await countersRes.json();
        setCounters(countersData);
      }

      // 2. Fetch limit events
      const eventsRes = await fetch(`${apiUrl}/api/admin/billing/limit-events?limit=50&page=${page}`, { headers });
      if (eventsRes.ok) {
        const eventsData = await eventsRes.json();
        setEvents(eventsData);
      }

      // 3. Fetch workspaces list for reconciliation dropdown
      const wsRes = await fetch(`${apiUrl}/api/admin/workspaces`, { headers });
      if (wsRes.ok) {
        const wsData = await wsRes.json();
        setWorkspaces(wsData || []);
        if (wsData && wsData.length > 0 && !selectedWorkspace) {
          setSelectedWorkspace(wsData[0].id);
        }
      }
    } catch (e: any) {
      toast.error(e.message || "Failed to load Call Admission data.");
    } finally {
      setLoading(false);
    }
  };

  const handleReconcile = async () => {
    if (!selectedWorkspace) {
      toast.error("Please select a workspace first.");
      return;
    }
    setReconciling(true);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const headers = { Authorization: `Bearer ${session.access_token}` };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

      const res = await fetch(`${apiUrl}/api/admin/billing/workspaces/${selectedWorkspace}/reconcile-counters`, {
        method: "POST",
        headers
      });

      if (!res.ok) throw new Error("Reconciliation failed.");
      const report = await res.json();
      
      if (report.success) {
        toast.success(`Reconciliation complete. Fixed: ${report.fixed}. Active Reservations: ${report.active_reservations}`);
        fetchCACData();
      } else {
        toast.error("Reconciliation execution encountered an error.");
      }
    } catch (e: any) {
      toast.error(e.message || "Reconciliation error.");
    } finally {
      setReconciling(false);
    }
  };

  useEffect(() => {
    fetchCACData();
  }, [page]);

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-black/50">
            <Layers className="h-3.5 w-3.5" />
            <span>Operational Safety</span>
          </div>
          <h1 className="text-4xl font-[340] tracking-[-0.03em] text-black">Call Admission Control</h1>
          <p className="max-w-2xl text-[14px] font-[320] leading-relaxed text-black/60">
            Monitor real-time concurrent call capacities, reconcile stale counters, and review outbound/inbound safety limits.
          </p>
        </div>
        <button
          onClick={fetchCACData}
          className="flex h-10 w-10 items-center justify-center rounded-[12px] border border-[#e6e6e6] bg-white transition hover:bg-[#f7f7f5]"
        >
          <RefreshCw className="h-4 w-4 text-black/60" />
        </button>
      </div>

      {loading ? (
        <div className="flex h-[40vh] items-center justify-center">
          <p className="font-mono text-[12px] uppercase tracking-widest text-black/40">
            Retrieving call admission logs...
          </p>
        </div>
      ) : (
        <div className="grid gap-8 lg:grid-cols-3">
          {/* Active Counters Summary */}
          <div className="lg:col-span-2 space-y-6">
            <div className="rounded-[20px] border border-[#e6e6e6] bg-white p-6 shadow-sm space-y-5">
              <h2 className="text-[16px] font-[340] text-black border-b border-[#e6e6e6] pb-3">
                Live Active Reservations
              </h2>

              <div className="grid gap-6 md:grid-cols-3">
                {/* Workspaces */}
                <div className="space-y-3">
                  <span className="text-[11px] font-mono uppercase text-black/40 block">Workspaces</span>
                  <div className="space-y-2 max-h-[200px] overflow-y-auto pr-1">
                    {counters && Object.keys(counters.workspace_active_calls).length > 0 ? (
                      Object.entries(counters.workspace_active_calls).map(([id, val]) => (
                        <div key={id} className="flex justify-between text-[13px] border-b border-[#f2f2f0] pb-1.5">
                          <span className="font-mono text-black/70 truncate max-w-[120px]">{id}</span>
                          <span className="font-semibold text-black">{val} calls</span>
                        </div>
                      ))
                    ) : (
                      <p className="text-[12px] text-black/40">No active calls</p>
                    )}
                  </div>
                </div>

                {/* Agents */}
                <div className="space-y-3">
                  <span className="text-[11px] font-mono uppercase text-black/40 block">Agents</span>
                  <div className="space-y-2 max-h-[200px] overflow-y-auto pr-1">
                    {counters && Object.keys(counters.agent_active_calls).length > 0 ? (
                      Object.entries(counters.agent_active_calls).map(([id, val]) => (
                        <div key={id} className="flex justify-between text-[13px] border-b border-[#f2f2f0] pb-1.5">
                          <span className="font-mono text-black/70 truncate max-w-[120px]">{id}</span>
                          <span className="font-semibold text-black">{val} calls</span>
                        </div>
                      ))
                    ) : (
                      <p className="text-[12px] text-black/40">No active calls</p>
                    )}
                  </div>
                </div>

                {/* SIP Trunks */}
                <div className="space-y-3">
                  <span className="text-[11px] font-mono uppercase text-black/40 block">SIP Trunks</span>
                  <div className="space-y-2 max-h-[200px] overflow-y-auto pr-1">
                    {counters && Object.keys(counters.trunk_active_calls).length > 0 ? (
                      Object.entries(counters.trunk_active_calls).map(([id, val]) => (
                        <div key={id} className="flex justify-between text-[13px] border-b border-[#f2f2f0] pb-1.5">
                          <span className="font-mono text-black/70 truncate max-w-[120px]">{id}</span>
                          <span className="font-semibold text-black">{val} calls</span>
                        </div>
                      ))
                    ) : (
                      <p className="text-[12px] text-black/40">No active calls</p>
                    )}
                  </div>
                </div>
              </div>
            </div>

            {/* Rejection Logs */}
            <div className="rounded-[20px] border border-[#e6e6e6] bg-white p-6 shadow-sm space-y-4">
              <h2 className="text-[16px] font-[340] text-black border-b border-[#e6e6e6] pb-3 flex items-center gap-2">
                <ShieldX className="h-4 w-4 text-red-500" />
                <span>Call Rejection Events Log</span>
              </h2>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-[13px]">
                  <thead>
                    <tr className="border-b border-[#e6e6e6] text-black/40 font-mono text-[10px] uppercase">
                      <th className="py-2.5">Time</th>
                      <th className="py-2.5">Workspace</th>
                      <th className="py-2.5">Call Type</th>
                      <th className="py-2.5">Limit/Value</th>
                      <th className="py-2.5 text-right">Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.length > 0 ? (
                      events.map((evt) => (
                        <tr key={evt.id} className="border-b border-[#f2f2f0] hover:bg-[#fcfcfb] transition-colors">
                          <td className="py-3 font-mono text-[11px] text-black/60">
                            {new Date(evt.created_at).toLocaleTimeString()}
                          </td>
                          <td className="py-3 font-mono text-[11px] text-black/70 truncate max-w-[100px]">
                            {evt.workspace_id}
                          </td>
                          <td className="py-3 font-medium text-black">
                            {evt.direction}
                          </td>
                          <td className="py-3 text-black/70">
                            {evt.limit_type} ({evt.current_value}/{evt.limit_value})
                          </td>
                          <td className="py-3 text-right text-red-600 font-medium">
                            {evt.rejection_reason}
                          </td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan={5} className="py-6 text-center text-black/40 font-mono text-[12px]">
                          No limit events logged.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              <div className="flex justify-between items-center pt-4 border-t border-[#e6e6e6]">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage(page - 1)}
                  className="px-3.5 py-1.5 rounded-[8px] border border-[#e6e6e6] text-[12px] bg-white hover:bg-[#fcfcfb] disabled:opacity-50"
                >
                  Previous
                </button>
                <span className="text-[12px] text-black/60">Page {page}</span>
                <button
                  disabled={events.length < 50}
                  onClick={() => setPage(page + 1)}
                  className="px-3.5 py-1.5 rounded-[8px] border border-[#e6e6e6] text-[12px] bg-white hover:bg-[#fcfcfb] disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            </div>
          </div>

          {/* Reconciliation Console */}
          <div className="space-y-6">
            <div className="rounded-[20px] border border-[#e6e6e6] bg-white p-6 shadow-sm space-y-5">
              <h2 className="text-[16px] font-[340] text-black border-b border-[#e6e6e6] pb-3 flex items-center gap-2">
                <ShieldAlert className="h-4 w-4 text-amber-500" />
                <span>Reconciliation Console</span>
              </h2>

              <p className="text-[13px] text-black/60 leading-relaxed">
                If call session tracking socket fails or Asterisk fails to notify end state, concurrency counters might drift. Reconcile counters to scan and rebuild active call allocations.
              </p>

              <div className="space-y-4">
                <div>
                  <label className="text-[11px] font-mono uppercase text-black/40 block mb-1.5">
                    Select Workspace to Audit
                  </label>
                  <select
                    value={selectedWorkspace}
                    onChange={(e) => setSelectedWorkspace(e.target.value)}
                    className="w-full h-10 px-3 rounded-[10px] border border-[#e6e6e6] bg-white text-[13px] text-black focus:outline-none focus:border-black"
                  >
                    {workspaces.map((ws) => (
                      <option key={ws.id} value={ws.id}>
                        {ws.name} ({ws.id.substring(0, 8)}...)
                      </option>
                    ))}
                  </select>
                </div>

                <button
                  onClick={handleReconcile}
                  disabled={reconciling}
                  className="w-full h-11 bg-black text-white rounded-[12px] text-[13px] font-medium transition hover:bg-black/90 disabled:opacity-60 flex items-center justify-center gap-2"
                >
                  {reconciling ? "Executing Reconciliation..." : "Execute Drift Audit & Fix"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
