import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { RefreshCw, Activity, AlertTriangle, ShieldCheck, Clock, Layers } from "lucide-react";
import { toast } from "sonner";

export const Route = createFileRoute("/_authenticated/admin/providers")({
  component: ProvidersManager,
});

interface ProviderMetric {
  provider: string;
  service_type: string;
  avg_latency: number;
  total_requests: number;
  error_count: number;
  success_rate: number;
}

interface ProviderEvent {
  id: string;
  provider: string;
  service_type: string;
  status: string;
  latency_ms: number;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
}

function ProvidersManager() {
  const [metrics, setMetrics] = useState<ProviderMetric[]>([]);
  const [events, setEvents] = useState<ProviderEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);

  const fetchProviderData = async () => {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const headers = { Authorization: `Bearer ${session.access_token}` };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

      // 1. Fetch provider health metrics summary
      const metricsRes = await fetch(`${apiUrl}/api/admin/providers/health`, { headers });
      if (metricsRes.ok) {
        const metricsData = await metricsRes.json();
        setMetrics(metricsData);
      }

      // 2. Fetch paginated events/traces
      const eventsRes = await fetch(`${apiUrl}/api/admin/providers/events?limit=50&page=${page}`, { headers });
      if (eventsRes.ok) {
        const eventsData = await eventsRes.json();
        setEvents(eventsData);
      }
    } catch (e: any) {
      toast.error(e.message || "Failed to load provider metrics.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProviderData();
  }, [page]);

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-black/50">
            <Activity className="h-3.5 w-3.5" />
            <span>AI Gateway Analytics</span>
          </div>
          <h1 className="text-4xl font-[340] tracking-[-0.03em] text-black">Provider Latency & Health</h1>
          <p className="max-w-2xl text-[14px] font-[320] leading-relaxed text-black/60">
            Monitor real-time response times, request volumes, success rates, and errors across LLM, STT, and TTS integrations.
          </p>
        </div>
        <button
          onClick={fetchProviderData}
          className="flex h-10 w-10 items-center justify-center rounded-[12px] border border-[#e6e6e6] bg-white transition hover:bg-[#f7f7f5]"
        >
          <RefreshCw className="h-4 w-4 text-black/60" />
        </button>
      </div>

      {loading ? (
        <div className="flex h-[40vh] items-center justify-center">
          <p className="font-mono text-[12px] uppercase tracking-widest text-black/40">
            Analyzing provider latency logs...
          </p>
        </div>
      ) : (
        <div className="space-y-8">
          {/* Provider Performance Cards */}
          <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
            {metrics.map((prov) => {
              const successClass = prov.success_rate >= 98 
                ? "text-green-600" 
                : prov.success_rate >= 90 
                  ? "text-amber-500" 
                  : "text-red-500";
                  
              return (
                <div key={`${prov.provider}-${prov.service_type}`} className="rounded-[20px] border border-[#e6e6e6] bg-white p-5 shadow-sm space-y-4">
                  <div className="flex justify-between items-start border-b border-[#e6e6e6] pb-3">
                    <div>
                      <span className="font-mono text-[11px] uppercase tracking-wider text-black/40 block">
                        {prov.service_type}
                      </span>
                      <h3 className="text-[16px] font-[360] text-black capitalize">
                        {prov.provider}
                      </h3>
                    </div>
                    <span className={`text-[12px] font-mono font-bold ${successClass}`}>
                      {prov.success_rate.toFixed(1)}%
                    </span>
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <span className="text-[11px] font-mono uppercase text-black/40 block">Avg Latency</span>
                      <div className="flex items-baseline gap-1 font-semibold text-black mt-0.5">
                        <Clock className="h-3.5 w-3.5 text-black/40 shrink-0" />
                        <span className="text-[15px]">{prov.avg_latency}</span>
                        <span className="text-[10px] text-black/50 font-normal">ms</span>
                      </div>
                    </div>

                    <div>
                      <span className="text-[11px] font-mono uppercase text-black/40 block">Errors</span>
                      <div className="flex items-baseline gap-1 font-semibold text-black mt-0.5">
                        <span className={`text-[15px] ${prov.error_count > 0 ? "text-red-500" : "text-black/80"}`}>
                          {prov.error_count}
                        </span>
                        <span className="text-[10px] text-black/50 font-normal">/ {prov.total_requests}</span>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Detailed Error Traces */}
          <div className="rounded-[20px] border border-[#e6e6e6] bg-white p-6 shadow-sm space-y-4">
            <h2 className="text-[16px] font-[340] text-black border-b border-[#e6e6e6] pb-3 flex items-center gap-2">
              <Layers className="h-4 w-4 text-black/50" />
              <span>Provider Transaction events & Error traces</span>
            </h2>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-[13px]">
                <thead>
                  <tr className="border-b border-[#e6e6e6] text-black/40 font-mono text-[10px] uppercase">
                    <th className="py-2.5">Timestamp</th>
                    <th className="py-2.5">Provider</th>
                    <th className="py-2.5">Service</th>
                    <th className="py-2.5">Latency</th>
                    <th className="py-2.5">Status</th>
                    <th className="py-2.5 text-right">Details</th>
                  </tr>
                </thead>
                <tbody>
                  {events.length > 0 ? (
                    events.map((evt) => (
                      <tr key={evt.id} className="border-b border-[#f2f2f0] hover:bg-[#fcfcfb] transition-colors">
                        <td className="py-3 font-mono text-[11px] text-black/60">
                          {new Date(evt.created_at).toLocaleString()}
                        </td>
                        <td className="py-3 font-medium text-black capitalize">
                          {evt.provider}
                        </td>
                        <td className="py-3 font-mono text-[11px] text-black/70">
                          {evt.service_type.toUpperCase()}
                        </td>
                        <td className="py-3 text-black/70 font-mono">
                          {evt.latency_ms} ms
                        </td>
                        <td className="py-3">
                          <span className={`rounded-full px-2 py-0.5 text-[9px] font-bold uppercase ${
                            evt.status === "success" 
                              ? "bg-green-50 text-green-700" 
                              : evt.status === "429_rate_limited" 
                                ? "bg-amber-50 text-amber-700" 
                                : "bg-red-50 text-red-700"
                          }`}>
                            {evt.status}
                          </span>
                        </td>
                        <td className="py-3 text-right max-w-xs truncate text-black/60 font-mono text-[11px]">
                          {evt.error_message || "-"}
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={6} className="py-6 text-center text-black/40 font-mono text-[12px]">
                        No logs or errors recorded.
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
      )}
    </div>
  );
}
