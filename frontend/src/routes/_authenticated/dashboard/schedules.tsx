import { useEffect, useState } from "react";
import { ScheduleTaskModal } from "@/components/dashboard/ScheduleTaskModal";
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
  Calendar,
  Clock,
  MoreVertical,
  Play,
  Pause,
  Trash2,
  Loader2,
  RefreshCw,
  FileText
} from "lucide-react";
import { supabase } from "@/lib/supabase";
import { useWorkspace } from "@/context/WorkspaceContext";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { toast } from "sonner";

export const Route = createFileRoute("/_authenticated/dashboard/schedules")({
  component: SchedulesPage,
});

function getStatusBadge(status: string) {
  const s = status.toLowerCase();
  if (s === "scheduled") {
    return <span className="rounded-full border border-[#dceeb1] bg-[#dceeb1]/30 px-3 py-1 text-[9px] font-mono uppercase tracking-[0.18em] text-[#1ea64a]">Scheduled</span>;
  }
  if (s === "running") {
    return <span className="animate-pulse rounded-full border border-black bg-black px-3 py-1 text-[9px] font-mono uppercase tracking-[0.18em] text-white">Executing</span>;
  }
  if (s === "paused") {
    return <span className="rounded-full border border-[#e6e6e6] bg-[#f7f7f5] px-3 py-1 text-[9px] font-mono uppercase tracking-[0.18em] text-black/40">Paused</span>;
  }
  if (s === "completed") {
    return <span className="rounded-full border border-blue-100 bg-blue-50 px-3 py-1 text-[9px] font-mono uppercase tracking-[0.18em] text-blue-600">Completed</span>;
  }
  if (s === "failed") {
    return <span className="rounded-full border border-red-100 bg-red-50 px-3 py-1 text-[9px] font-mono uppercase tracking-[0.18em] text-red-600">Failed</span>;
  }
  return <span className="rounded-full border border-[#e6e6e6] bg-[#f7f7f5] px-3 py-1 text-[9px] font-mono uppercase tracking-[0.18em] text-black/40">{status}</span>;
}

function SchedulesPage() {
  const { workspaceId: contextWsId, authHeaders: contextHeaders, loading: contextLoading } = useWorkspace();
  const navigate = useNavigate();
  const [schedules, setSchedules] = useState<any[]>([]);
  const [agents, setAgents] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [authHeaders, setAuthHeaders] = useState<any>(null);

  const apiUrl = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

  const fetchSchedules = async (wsId: string, headers: any) => {
    try {
      const res = await fetch(`${apiUrl}/api/v1/workspaces/${wsId}/schedules`, { headers });
      const data = await res.json();
      setSchedules(data);
    } catch (err) {
      console.error("Failed to fetch schedules:", err);
    }
  };

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
        // Fetch agents for display names
        const agentsRes = await fetch(`${apiUrl}/api/v1/workspaces/${contextWsId}/agents`, { headers: contextHeaders! });
        const agentsData = await agentsRes.json();
        setAgents(agentsData);

        await fetchSchedules(contextWsId!, contextHeaders!);
      } catch (err) {
        console.error("Initialization failed:", err);
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [contextWsId, contextHeaders, contextLoading, apiUrl]);

  const handleAction = async (action: string, id: string) => {
    if (!workspaceId || !authHeaders) return;

    try {
      let endpoint = `${apiUrl}/api/v1/scheduled-tasks/${id}`;
      let method = "POST";

      if (action === "pause") endpoint += "/pause";
      else if (action === "resume") endpoint += "/resume";
      else if (action === "run-now") {
        endpoint += "/run-now";
        toast.info("Triggering call — this may take a moment...");
      } else if (action === "delete") {
        method = "DELETE";
      }

      const res = await fetch(endpoint, { method, headers: authHeaders });
      if (res.ok) {
        const result = await res.json();
        if (action === "run-now") {
          if (result.status === "failed") {
            toast.error("Call failed — open View Logs for the error details");
          } else {
            toast.success("Call triggered successfully");
          }
        } else {
          toast.success(`Task ${action}d successfully`);
        }
        fetchSchedules(workspaceId, authHeaders);
      } else {
        const err = await res.json().catch(() => ({}));
        toast.error(err.detail || `Failed to ${action} task`);
      }
    } catch (err) {
      toast.error("Operation failed — check backend is running");
    }
  };

  const getAgentName = (id: string) => {
    const agent = agents.find(a => a.id === id);
    return agent ? agent.name : "Unknown Agent";
  };

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-8 px-4 py-3 md:px-5 md:py-4">
      <div className="space-y-8">
        
        {/* Header */}
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
          <div className="space-y-3">
            <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-[#999999]">
              <Calendar className="h-3.5 w-3.5" />
              <span>Temporal Orchestration</span>
            </div>
            <h1 className="text-4xl font-[340] tracking-[-0.03em] text-black md:text-5xl">
              Schedules
            </h1>
            <p className="max-w-2xl text-[15px] font-[330] leading-relaxed text-black/60">
              Manage automated intelligence cycles and recurring voice deployments across global time zones.
            </p>
          </div>
          {workspaceId && authHeaders && (
            <ScheduleTaskModal 
              workspaceId={workspaceId} 
              agents={agents} 
              authHeaders={authHeaders}
              onSuccess={() => fetchSchedules(workspaceId, authHeaders)} 
            />
          )}
        </div>

        {/* Data Table */}
        <div className="overflow-hidden rounded-[20px] border border-[#e6e6e6] bg-white shadow-lg shadow-black/5">
          <div className="flex flex-col justify-between gap-3 border-b border-[#f1f1f1] bg-[#f7f7f5]/30 p-4 sm:flex-row">
            <div className="relative w-full max-w-sm">
              <Search className="absolute left-3.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-black/20" />
              <Input
                type="search"
                placeholder="Search sequences..."
                className="h-9 rounded-full border-[#e6e6e6] bg-white pl-10 text-[13px] font-[330] transition-all focus:border-black"
              />
            </div>
            <div className="flex gap-2.5">
              <Button variant="ghost" className="h-9 gap-2 rounded-full border border-[#e6e6e6] bg-white px-4 text-[12px] font-[480] hover:bg-[#f7f7f5]">
                <Filter className="h-4 w-4 text-black/40" />
                Filter
              </Button>
            </div>
          </div>
          
          <div className="overflow-x-auto">
            {loading ? (
               <div className="flex h-80 flex-col items-center justify-center space-y-4">
                 <Loader2 className="h-10 w-10 animate-spin text-black opacity-20" />
                 <p className="font-mono text-[12px] uppercase tracking-[0.2em] opacity-40">Synchronizing clock...</p>
               </div>
            ) : (
              <Table>
                <TableHeader className="bg-[#f7f7f5]/30">
                  <TableRow className="border-[#f1f1f1] hover:bg-transparent">
                    <TableHead className="h-12 pl-8 font-mono text-[10px] uppercase tracking-[0.16em] text-black/40">Sequence</TableHead>
                    <TableHead className="h-12 font-mono text-[10px] uppercase tracking-[0.16em] text-black/40">Agent</TableHead>
                    <TableHead className="h-12 font-mono text-[10px] uppercase tracking-[0.16em] text-black/40">Type</TableHead>
                    <TableHead className="h-12 font-mono text-[10px] uppercase tracking-[0.16em] text-black/40">Next Run</TableHead>
                    <TableHead className="h-12 font-mono text-[10px] uppercase tracking-[0.16em] text-black/40">Status</TableHead>
                    <TableHead className="h-12 font-mono text-[10px] uppercase tracking-[0.16em] text-black/40">Recurrence</TableHead>
                    <TableHead className="h-12 pr-8 text-right font-mono text-[10px] uppercase tracking-[0.16em] text-black/40">Control</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {schedules.length > 0 ? (
                    schedules.map((task) => (
                      <TableRow 
                        key={task.id} 
                        className="border-[#f1f1f1] hover:bg-[#f7f7f5]/50 group transition-all cursor-pointer"
                        onClick={(e) => {
                          // Don't navigate if clicking the dropdown button
                          if ((e.target as HTMLElement).closest('button')) return;
                          navigate({ to: `/dashboard/schedules/${task.id}` });
                        }}
                      >
                        <TableCell className="py-4 pl-8">
                          <div className="flex flex-col">
                            <span className="text-[15px] font-[540] text-black">{task.title}</span>
                            <span className="font-mono text-[10px] text-black/30 uppercase tracking-wider">{task.id.slice(0, 8)}</span>
                          </div>
                        </TableCell>
                        <TableCell className="py-4 text-[14px] font-[330] text-black/70">
                          {getAgentName(task.agent_id)}
                        </TableCell>
                        <TableCell className="py-4">
                          <span className="rounded-full border border-[#e6e6e6] bg-white px-3 py-1 text-[9px] font-mono uppercase tracking-[0.18em] text-black">{task.task_type}</span>
                        </TableCell>
                        <TableCell className="py-4">
                          <div className="flex items-center gap-2 font-mono text-[12px] text-black/60">
                            <Clock className="h-3 w-3 opacity-30" />
                            {task.next_run_at ? new Date(task.next_run_at).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' }) : "N/A"}
                          </div>
                        </TableCell>
                        <TableCell className="py-4">
                          {getStatusBadge(task.status)}
                        </TableCell>
                        <TableCell className="py-4 text-[12px] font-[330] text-black/40 italic">
                          {task.recurrence_rule || "Single Run"}
                        </TableCell>
                        <TableCell className="py-4 pr-8 text-right">
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button variant="ghost" className="h-8 w-8 p-0 rounded-full hover:bg-black/5">
                                <MoreVertical className="h-4 w-4 text-black/40" />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className="w-44 rounded-[12px] border-[#e6e6e6] shadow-xl">
                              <DropdownMenuItem onClick={() => navigate({ to: `/dashboard/schedules/${task.id}` })} className="gap-2 text-[13px]">
                                <FileText className="h-3.5 w-3.5" /> View Logs
                              </DropdownMenuItem>
                              <DropdownMenuItem onClick={() => handleAction("run-now", task.id)} className="gap-2 text-[13px]">
                                <RefreshCw className="h-3.5 w-3.5" /> Run Now
                              </DropdownMenuItem>
                              {task.status === "paused" ? (
                                <DropdownMenuItem onClick={() => handleAction("resume", task.id)} className="gap-2 text-[13px]">
                                  <Play className="h-3.5 w-3.5" /> Resume
                                </DropdownMenuItem>
                              ) : (
                                <DropdownMenuItem onClick={() => handleAction("pause", task.id)} className="gap-2 text-[13px]">
                                  <Pause className="h-3.5 w-3.5" /> Pause
                                </DropdownMenuItem>
                              )}
                              <DropdownMenuItem onClick={() => handleAction("delete", task.id)} className="gap-2 text-[13px] text-red-500 focus:text-red-500">
                                <Trash2 className="h-3.5 w-3.5" /> Cancel
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow className="hover:bg-transparent">
                      <TableCell colSpan={7} className="h-48 text-center">
                        <div className="flex flex-col items-center justify-center space-y-3">
                          <Calendar className="h-10 w-10 text-black/5" />
                          <p className="text-[15px] font-[330] italic text-black/30">No temporal sequences initialized in this sector.</p>
                          <Button variant="outline" className="h-9 rounded-full border-[#e6e6e6] px-6 text-[12px] font-[480]">
                            Initialize First Sequence
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
