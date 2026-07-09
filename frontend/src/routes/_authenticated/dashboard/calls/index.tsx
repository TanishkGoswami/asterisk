import { useEffect, useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Search,
  Filter,
  Download,
  ChevronRight,
  Loader2,
  History
} from "lucide-react";
import { useWorkspace } from "@/context/WorkspaceContext";

export const Route = createFileRoute("/_authenticated/dashboard/calls/")({
  component: CallsPage,
});

function getStatusBadge(status: string) {
  const s = status.toLowerCase();
  if (s.includes("completed") || s.includes("resolved") || s.includes("settled")) {
    return <span className="rounded-full border border-[#dceeb1] bg-[#dceeb1]/30 px-3 py-1 text-[9px] font-mono uppercase tracking-[0.18em] text-[#1ea64a]">Settled</span>;
  }
  if (s.includes("ringing") || s.includes("in_progress")) {
    return <span className="animate-pulse rounded-full border border-black bg-black px-3 py-1 text-[9px] font-mono uppercase tracking-[0.18em] text-white">Active</span>;
  }
  if (s.includes("failed") || s.includes("busy") || s.includes("no_answer") || s.includes("canceled")) {
    return <span className="rounded-full border border-[#efd4d4] bg-[#efd4d4]/30 px-3 py-1 text-[9px] font-mono uppercase tracking-[0.18em] text-red-500">Terminated</span>;
  }
  return <span className="rounded-full border border-[#e6e6e6] bg-[#f7f7f5] px-3 py-1 text-[9px] font-mono uppercase tracking-[0.18em] text-black/40">{status}</span>;
}

function getSentimentBadge(sentiment: number | null) {
  if (sentiment === null) return <span className="text-[13px] font-[330] text-black/30">Neutral</span>;
  if (sentiment > 0.6) return <span className="text-[13px] font-[540] text-[#1ea64a]">Positive</span>;
  if (sentiment < 0.4) return <span className="text-[13px] font-[540] text-red-500">Negative</span>;
  return <span className="text-[13px] font-[330] text-black/30">Neutral</span>;
}

function CallsPage() {
  const { workspaceId: contextWsId, authHeaders: contextHeaders, loading: contextLoading } = useWorkspace();
  const navigate = useNavigate();
  const [calls, setCalls] = useState<any[]>([]);
  const [, setWorkspaceId] = useState<string | null>(null);
  const [, setAuthHeaders] = useState<Record<string, string> | null>(null);
  const [loading, setLoading] = useState(true);

  const apiUrl = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

  useEffect(() => {
    if (contextLoading) return;
    if (!contextWsId || !contextHeaders) {
      setLoading(false);
      return;
    }

    setWorkspaceId(contextWsId);
    setAuthHeaders(contextHeaders);

    async function init() {
      try {
        const callsRes = await fetch(`${apiUrl}/api/v1/workspaces/${contextWsId}/calls`, { headers: contextHeaders! });
        const data = await callsRes.json();
        setCalls(data);
      } catch (err) {
        console.error("Failed to load calls:", err);
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [contextWsId, contextHeaders, contextLoading, apiUrl]);

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-8 px-4 py-3 md:px-5 md:py-4">
      <div className="space-y-8">
        
        {/* Header */}
        <div className="space-y-3">
          <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-[#999999]">
            <History className="h-3.5 w-3.5" />
            <span>Telemetric Records</span>
          </div>
          <h1 className="text-4xl font-[340] tracking-[-0.03em] text-black md:text-5xl">
            Call History
          </h1>
          <p className="max-w-2xl text-[15px] font-[330] leading-relaxed text-black/60">
            Comprehensive audit log of all intelligence interactions and high-fidelity voice transmissions processed by the neural engine.
          </p>
        </div>

        {/* Data Table */}
        <div className="overflow-hidden rounded-[20px] border border-[#e6e6e6] bg-white shadow-lg shadow-black/5">
          <div className="flex flex-col justify-between gap-3 border-b border-[#f1f1f1] bg-[#f7f7f5]/30 p-4 sm:flex-row">
            <div className="relative w-full max-w-sm">
              <Search className="absolute left-3.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-black/20" />
              <Input
                type="search"
                placeholder="Search audit identifier..."
                className="h-9 rounded-full border-[#e6e6e6] bg-white pl-10 text-[13px] font-[330] transition-all focus:border-black"
              />
            </div>
            <div className="flex gap-2.5">
              <Button variant="ghost" className="h-9 gap-2 rounded-full border border-[#e6e6e6] bg-white px-4 text-[12px] font-[480] hover:bg-[#f7f7f5]">
                <Filter className="h-4 w-4 text-black/40" />
                Filter Logs
              </Button>
              <Button variant="ghost" className="h-9 gap-2 rounded-full border border-[#e6e6e6] bg-white px-4 text-[12px] font-[480] hover:bg-[#f7f7f5]">
                <Download className="h-4 w-4 text-black/40" />
                Export CSV
              </Button>
            </div>
          </div>
          
          <div className="overflow-x-auto">
            {loading ? (
               <div className="flex h-80 flex-col items-center justify-center space-y-4">
                 <Loader2 className="h-10 w-10 animate-spin text-black opacity-20" />
                 <p className="font-mono text-[12px] uppercase tracking-[0.2em] opacity-40">Decrypting telemetry...</p>
              </div>
            ) : (
              <Table>
                <TableHeader className="bg-[#f7f7f5]/30">
                  <TableRow className="border-[#f1f1f1] hover:bg-transparent">
                    <TableHead className="h-12 pl-8 font-mono text-[10px] uppercase tracking-[0.16em] text-black/40">Identifier</TableHead>
                    <TableHead className="h-12 font-mono text-[10px] uppercase tracking-[0.16em] text-black/40">Participant</TableHead>
                    <TableHead className="h-12 font-mono text-[10px] uppercase tracking-[0.16em] text-black/40">Mode</TableHead>
                    <TableHead className="h-12 font-mono text-[10px] uppercase tracking-[0.16em] text-black/40">Timing</TableHead>
                    <TableHead className="h-12 font-mono text-[10px] uppercase tracking-[0.16em] text-black/40">Outcome</TableHead>
                    <TableHead className="h-12 font-mono text-[10px] uppercase tracking-[0.16em] text-black/40">Analysis</TableHead>
                    <TableHead className="h-12 font-mono text-[10px] uppercase tracking-[0.16em] text-black/40">Credits</TableHead>
                    <TableHead className="h-12 font-mono text-[10px] uppercase tracking-[0.16em] text-black/40">Timestamp</TableHead>
                    <TableHead className="h-12 pr-8 text-right font-mono text-[10px] uppercase tracking-[0.16em] text-black/40">Action</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {calls.length > 0 ? (
                    calls.map((call) => (
                        <TableRow
                          key={call.id}
                          className="border-[#f1f1f1] cursor-pointer hover:bg-[#f7f7f5]/50 group transition-all"
                          onClick={() => navigate({ to: `/dashboard/calls/${call.id}` })}
                        >
                          <TableCell className="max-w-[130px] truncate py-4 pl-8 font-mono text-[11px] text-black/40">
                           {call.id.slice(0, 12)}...
                          </TableCell>
                          <TableCell className="py-4 text-[15px] font-[540] text-black">
                            {call.caller_phone_number || "System Protocol"}
                          </TableCell>
                          <TableCell className="py-4">
                            <span className="rounded-full border border-[#e6e6e6] bg-white px-3 py-1 text-[9px] font-mono uppercase tracking-[0.18em] text-black">{call.direction}</span>
                          </TableCell>
                          <TableCell className="py-4 font-mono text-[13px] text-black/60">
                            {call.actual_duration || 0}s
                          </TableCell>
                          <TableCell className="py-4">
                            {getStatusBadge(call.status)}
                          </TableCell>
                          <TableCell className="py-4">
                            {getSentimentBadge(call.sentiment_score)}
                          </TableCell>
                          <TableCell className="py-4 font-mono text-[13px] text-black/60">
                            {call.estimated_cost !== undefined && call.estimated_cost !== null
                              ? parseFloat(call.estimated_cost).toFixed(2)
                              : "0.00"}
                          </TableCell>
                          <TableCell className="py-4 text-[13px] font-[330] text-black/40">
                            {new Date(call.created_at).toLocaleDateString()}
                          </TableCell>
                          <TableCell className="py-4 pr-8 text-right">
                            <div className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-transparent transition-all group-hover:border-[#e6e6e6] group-hover:bg-white">
                              <ChevronRight className="h-4 w-4 text-black/20 group-hover:text-black" />
                            </div>
                          </TableCell>
                        </TableRow>
                    ))
                  ) : (
                    <TableRow className="hover:bg-transparent">
                      <TableCell colSpan={9} className="h-48 text-center text-[15px] font-[330] italic text-black/30">
                        Null telemetric records in current sector.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            )}
          </div>
          
           <div className="flex justify-center border-t border-[#f1f1f1] bg-[#f7f7f5]/20 p-4">
              <Button variant="ghost" className="h-9 rounded-full border border-transparent px-6 text-[12px] font-[480] text-black/40 transition-all hover:border-[#e6e6e6] hover:bg-white hover:text-black">
                Access Archival Records
              </Button>
           </div>
        </div>
      </div>
    </div>
  );
}
