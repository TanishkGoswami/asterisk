import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import {
  Plus,
  PhoneCall,
  Settings,
  MoreVertical,
  Loader2,
  Trash2,
  AudioLines,
  Search,
  CheckCircle2,
  Clock,
  Volume2,
  User,
  ClipboardList,
  Bot,
} from "lucide-react";


import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { supabase } from "@/lib/supabase";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useWorkspace } from "@/context/WorkspaceContext";

export const Route = createFileRoute("/_authenticated/dashboard/agents/")({
  component: AgentsPage,
});

const TERMINAL_STATUSES = ["completed", "failed", "no_answer", "canceled", "busy"];

function AgentsPage() {
  const { workspaceId: contextWsId, authHeaders: contextHeaders, loading: contextLoading } = useWorkspace();
  const [agents, setAgents] = useState<any[]>([]);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [authHeaders, setAuthHeaders] = useState<Record<string, string> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [testCallAgent, setTestCallAgent] = useState<any | null>(null);
  const [testCallNumber, setTestCallNumber] = useState("");
  const [countryCode, setCountryCode] = useState("+91");
  const [testCalling, setTestCalling] = useState(false);
  const [testCallResult, setTestCallResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [isEndingCall, setIsEndingCall] = useState(false);

  // Live call tracking state
  const [activeCallId, setActiveCallId] = useState<string | null>(null);
  const [callRecord, setCallRecord] = useState<any | null>(null);
  const [transcriptMessages, setTranscriptMessages] = useState<any[]>([]);
  const [callTime, setCallTime] = useState<number>(0);

  const apiUrl = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

  // Connection timer effect
  useEffect(() => {
    let interval: any;
    if (
      activeCallId &&
      callRecord &&
      !TERMINAL_STATUSES.includes(callRecord.status)
    ) {
      interval = setInterval(() => {
        setCallTime((prev) => prev + 1);
      }, 1000);
    }
    return () => clearInterval(interval);
  }, [activeCallId, callRecord]);

  // Polling fallback: re-fetch call status every 3s while call is active
  // This catches cases where Supabase realtime misses the status callback update
  useEffect(() => {
    if (!activeCallId || !callRecord) return;
    if (TERMINAL_STATUSES.includes(callRecord.status)) return;

    const pollInterval = setInterval(async () => {
      try {
        const { data } = await supabase
          .from("calls")
          .select("id, status, ended_at, metadata")
          .eq("id", activeCallId)
          .single();
        if (data) {
          setCallRecord((prev: any) => ({ ...prev, ...data }));
        }
      } catch (err) {
        // polling errors are non-fatal, ignore
      }
    }, 3000);

    return () => clearInterval(pollInterval);
  }, [activeCallId, callRecord?.status]);

  // Fetch initial call state and messages
  const fetchInitialCallData = useCallback(async (callId: string) => {
    try {
      const { data: callData } = await supabase
        .from("calls")
        .select("*")
        .eq("id", callId)
        .single();
      if (callData) {
        setCallRecord(callData);
      }
      const { data: messagesData } = await supabase
        .from("call_messages")
        .select("*")
        .eq("call_id", callId)
        .order("sequence_number", { ascending: true });
      if (messagesData) {
        setTranscriptMessages(messagesData);
      }
    } catch (err) {
      console.error("Error fetching call data:", err);
    }
  }, []);

  // Supabase realtime channel subscription
  useEffect(() => {
    if (!activeCallId) return;

    fetchInitialCallData(activeCallId);

    // Subscribe to call row updates
    const callChannel = supabase
      .channel(`call_changes_${activeCallId}`)
      .on(
        "postgres_changes",
        {
          event: "UPDATE",
          schema: "public",
          table: "calls",
          filter: `id=eq.${activeCallId}`,
        },
        (payload: any) => {
          setCallRecord(payload.new);
        }
      )
      .subscribe();

    // Subscribe to new call message inserts
    const messagesChannel = supabase
      .channel(`call_messages_changes_${activeCallId}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "call_messages",
          filter: `call_id=eq.${activeCallId}`,
        },
        (payload: any) => {
          setTranscriptMessages((prev) => {
            if (prev.some((m) => m.id === payload.new.id)) return prev;
            return [...prev, payload.new].sort((a, b) => a.sequence_number - b.sequence_number);
          });
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(callChannel);
      supabase.removeChannel(messagesChannel);
    };
  }, [activeCallId, fetchInitialCallData]);

  // Reset function when closing dialog
  const handleCloseDialog = async (open: boolean) => {
    if (!open) {
      if (activeCallId) {
        try {
          await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/calls/${activeCallId}/end`, {
            method: "POST",
            headers: authHeaders || undefined,
          });
        } catch (err) {
          console.error("Error ending call on close:", err);
        }
      }
      setTestCallAgent(null);
      setActiveCallId(null);
      setCallRecord(null);
      setTranscriptMessages([]);
      setCallTime(0);
      setTestCallResult(null);
      setIsEndingCall(false);
    }
  };

  const endCallSession = async () => {
    if (!activeCallId) return;
    setIsEndingCall(true);
    // Optimistically update UI immediately so the button reacts instantly
    setCallRecord((prev: any) => prev ? { ...prev, status: "canceled" } : prev);
    try {
      // Ensure we have auth headers even if state hasn't hydrated
      let headers = authHeaders;
      let wsId = workspaceId;
      if (!headers || !wsId) {
        const { data: { session } } = await (await import("@/lib/supabase")).supabase.auth.getSession();
        if (session) {
          headers = {
            "Content-Type": "application/json",
            Authorization: `Bearer ${session.access_token}`,
            "ngrok-skip-browser-warning": "true",
          };
          // workspaceId must already be set if we placed a call — fall through
        }
      }
      if (!headers || !wsId) {
        console.error("[EndSession] Missing auth headers or workspaceId, cannot end call");
        return;
      }
      const res = await fetch(`${apiUrl}/api/v1/workspaces/${wsId}/calls/${activeCallId}/end`, {
        method: "POST",
        headers,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        console.error("[EndSession] API error:", res.status, body);
      }
      // Sync actual status from DB
      fetchInitialCallData(activeCallId);
    } catch (err) {
      console.error("[EndSession] Error ending call:", err);
    } finally {
      setIsEndingCall(false);
    }
  };

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  };

  const getStepStatus = (step: "dialing" | "ringing" | "connected" | "completed") => {
    if (!callRecord) return "pending";
    const status = callRecord.status;

    if (step === "dialing") {
      return ["ringing", "in_progress", "completed", "failed", "no_answer", "canceled", "busy"].includes(status)
        ? "completed"
        : "active";
    }
    if (step === "ringing") {
      if (["in_progress", "completed", "failed", "no_answer", "canceled", "busy"].includes(status)) {
        return "completed";
      }
      return status === "ringing" ? "active" : "pending";
    }
    if (step === "connected") {
      if (["completed", "failed", "no_answer", "canceled", "busy"].includes(status)) {
        return "completed";
      }
      return status === "in_progress" ? "active" : "pending";
    }
    if (step === "completed") {
      return ["completed", "failed", "no_answer", "canceled", "busy"].includes(status) ? "completed" : "pending";
    }
    return "pending";
  };

  const fetchAgents = useCallback(async (wsId: string, headers: Record<string, string>) => {
    const res = await fetch(`${apiUrl}/api/v1/workspaces/${wsId}/agents`, { headers });
    if (!res.ok) throw new Error(`Failed to load agents: ${res.status}`);
    return res.json();
  }, [apiUrl]);

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
        setError(null);
        const data = await fetchAgents(contextWsId!, contextHeaders!);
        setAgents(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load agents");
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [contextWsId, contextHeaders, contextLoading, fetchAgents]);

  const handleDelete = async (agentId: string) => {
    if (!workspaceId || !authHeaders) return;
    try {
      const res = await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/agents/${agentId}`, {
        method: "DELETE",
        headers: authHeaders,
      });
      if (!res.ok) throw new Error(`Delete failed: ${res.status}`);
      setAgents((prev) => prev.filter((a) => a.id !== agentId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete agent");
    } finally {
      setConfirmDeleteId(null);
    }
  };

  const handleTestCall = async () => {
    if (!workspaceId || !authHeaders || !testCallAgent || !testCallNumber.trim()) return;
    setTestCalling(true);
    setTestCallResult(null);
    setCallTime(0);
    setCallRecord({ status: "ringing" }); // set initial local status to switch views
    const targetNumber = testCallNumber.trim();
    const fullNumber = targetNumber.startsWith("+") ? targetNumber : `${countryCode}${targetNumber}`;
    try {
      const res = await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/agents/${testCallAgent.id}/test-call`, {
        method: "POST",
        headers: authHeaders,
        body: JSON.stringify({ to_number: fullNumber }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `Error ${res.status}`);
      setTestCallResult({ ok: true, message: "Calling... check your mobile!" });
      if (data.call_id) {
        setActiveCallId(data.call_id);
      }
    } catch (err) {
      setTestCallResult({ ok: false, message: err instanceof Error ? err.message : "Test call failed" });
      setCallRecord(null); // revert status if failed
    } finally {
      setTestCalling(false);
    }
  };

  const agentToDelete = agents.find((a) => a.id === confirmDeleteId);

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-8 px-4 py-3 md:px-5 md:py-4">
      <div className="space-y-8">

        {/* Header Section */}
        <div className="flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
          <div className="space-y-3">
            <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-[#999999]">
              <Bot className="h-3.5 w-3.5" />
              <span>Agent Directory</span>
            </div>
            <h1 className="text-4xl font-[340] tracking-[-0.03em] text-black md:text-5xl">
              AI Agents
            </h1>
            <p className="max-w-2xl text-[15px] font-[330] leading-relaxed text-black/60">
              Your specialized voice personas, ready to represent your brand 24/7 with human-like intelligence.
            </p>
          </div>
          <Button
            asChild
            className="h-9 shrink-0 rounded-full bg-black px-5 text-[13px] font-medium text-white transition-all hover:bg-black/90"
          >
            <Link to="/dashboard/agents/new" search={{ agentId: undefined }}>
              <Plus className="mr-2 h-4 w-4" />
              Create New Agent
            </Link>
          </Button>
        </div>

        {loading ? (
          <div className="flex flex-col items-center justify-center space-y-5 py-24">
            <Loader2 className="h-10 w-10 animate-spin text-black opacity-20" />
            <p className="font-mono text-[12px] uppercase tracking-widest opacity-40">Loading neural profiles...</p>
          </div>
        ) : error ? (
          <div className="flex flex-col gap-3 rounded-[20px] border border-[#e6e6e6] bg-[#efd4d4]/10 p-8 text-black">
            <h2 className="text-[20px] font-bold">Initialization Error</h2>
            <p className="text-[14px] font-[320] opacity-60">{error}</p>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {agents.map((agent) => (
              <div
                key={agent.id}
                className="group flex flex-col gap-3 rounded-xl border border-[#e6e6e6] bg-white p-4 transition-all duration-300 hover:border-black hover:shadow-sm"
              >
                {/* Top Row: Identity */}
                <div className="flex items-center gap-2.5">
                  <div className="flex h-9 w-9 items-center justify-center rounded-full border border-[#e6e6e6] bg-[#f7f7f5]">
                    <AudioLines className="h-4 w-4 text-black" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="text-[14px] font-bold leading-tight tracking-tight text-black truncate">{agent.name}</h3>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <div className="h-1.5 w-1.5 rounded-full bg-[#1ea64a] pulse-dot" />
                      <span className="text-[8.5px] font-mono uppercase tracking-[0.12em] text-muted-foreground leading-none">
                        Active • {agent.language}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Stats Section */}
                {/* Action Grid */}
                <div className="flex flex-col gap-1.5 mt-1">
                  {/* Top Row: Configure Button spans full width */}
                  <div className="w-full">
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-8 rounded-lg border-[#e6e6e6] hover:bg-[#f7f7f5] hover:text-black text-[11px] font-semibold gap-1.5 justify-center w-full"
                      asChild
                    >
                      <Link to="/dashboard/agents/new" search={{ agentId: agent.id }}>
                        <Settings className="h-3 w-3 text-black/60" />
                        Configure
                      </Link>
                    </Button>
                  </div>

                  {/* Hidden Playground Button (Commented out / Hidden from layout) */}
                  {false && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-8 rounded-lg border-[#e6e6e6] hover:bg-[#f7f7f5] hover:text-black text-[11px] font-semibold gap-1.5 justify-center w-full"
                      asChild
                    >
                      <Link to="/dashboard/qa" search={{ agentId: agent.id }}>
                        <Search className="h-3 w-3 text-black/60" />
                        Playground
                      </Link>
                    </Button>
                  )}

                  {/* Bottom Row: Test Call and Delete side-by-side */}
                  <div className="grid grid-cols-2 gap-1.5">
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-8 rounded-lg border-[#e6e6e6] hover:bg-[#f7f7f5] hover:text-black text-[11px] font-semibold gap-1.5 justify-center w-full"
                      onClick={() => setTestCallAgent(agent)}
                    >
                      <PhoneCall className="h-3 w-3 text-black/60" />
                      Test Call
                    </Button>

                    <Button
                      variant="outline"
                      size="sm"
                      className="h-8 rounded-lg border-red-100 text-red-500 hover:bg-red-50/50 hover:border-red-200 hover:text-red-600 text-[11px] font-semibold gap-1.5 justify-center w-full"
                      onClick={() => setConfirmDeleteId(agent.id)}
                    >
                      <Trash2 className="h-3 w-3 text-red-500" />
                      Delete
                    </Button>
                  </div>
                </div>

                {/* Footer */}
                <div className="text-[10px] font-normal text-[#999999] pt-1">
                  Created {new Date(agent.created_at).toLocaleDateString()}
                </div>
              </div>
            ))}

            {/* Empty State / Create Card */}
            <Link
              to="/dashboard/agents/new"
              search={{ agentId: undefined }}
              className="group flex min-h-[220px] flex-col items-center justify-center rounded-xl border-2 border-dashed border-[#e6e6e6] p-4 text-center transition-all duration-300 hover:border-black hover:bg-[#f7f7f5]"
            >
              <div className="mb-3 flex h-7 w-7 items-center justify-center rounded-full border border-[#e6e6e6] bg-[#f7f7f5] text-black">
                <Plus className="h-3.5 w-3.5" />
              </div>
              <h4 className="mb-1 text-[14px] font-bold text-black">Deploy New Agent</h4>
              <p className="max-w-[180px] text-[11px] font-[330] text-[#000000] opacity-50">Expand your fleet with a custom persona.</p>
            </Link>
          </div>
        )}

        <Dialog open={!!testCallAgent} onOpenChange={handleCloseDialog}>
          <DialogContent className={`${activeCallId ? "sm:max-w-4xl w-full" : "sm:max-w-md"} max-h-[95vh] overflow-y-auto rounded-[24px] border-[#e6e6e6] p-6 md:p-8 bg-white shadow-2xl transition-all duration-300`}>
            <DialogHeader className="space-y-3">
              <DialogTitle className="text-[40px] font-medium leading-tight tracking-tight text-center text-black">
                {activeCallId ? "Live Test Call" : "Test Call"}
              </DialogTitle>
              <DialogDescription className="text-center text-[15px] font-[320] text-neutral-500 leading-normal max-w-xs mx-auto">
                {activeCallId
                  ? `Monitoring call with ${testCallAgent?.name}`
                  : "Connect your physical phone to your AI agent instance."}
              </DialogDescription>
            </DialogHeader>

            {activeCallId ? (
              <div className="space-y-6 py-4">

                {/* Terminal state banner — shown when call ends from provider side */}
                {callRecord && TERMINAL_STATUSES.includes(callRecord.status) && callRecord.status !== "completed" && (
                  <div className="flex items-center gap-3 rounded-xl border border-rose-100 bg-rose-50 px-5 py-3.5">
                    <div className="h-2 w-2 rounded-full bg-rose-500 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-[13px] font-semibold text-rose-700">
                        Call ended — {callRecord.status === "failed" ? "Application error" : callRecord.status === "no_answer" ? "No answer" : "Canceled"}
                      </p>
                      <p className="text-[11px] text-rose-500 font-[320]">
                        The call was terminated by the provider. Close this dialog or start a new call.
                      </p>
                    </div>
                  </div>
                )}
                <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
                  {/* Left Column: Latency Monitor */}
                  <div className="md:col-span-5 rounded-[20px] border border-[#e6e6e6] bg-[#fcfcfc] p-6 flex flex-col justify-between min-h-[380px]">
                    <div>
                      <div className="flex items-center justify-between border-b border-[#f1f1f1] pb-4 mb-6">
                        <div className="flex items-center gap-2 font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-neutral-400">
                          <Clock className="h-4 w-4 text-neutral-400" />
                          Latency Monitor
                        </div>
                        <div className="font-mono text-[16px] font-bold text-black bg-[#f1f1f1] px-2.5 py-0.5 rounded-md">
                          {formatTime(callTime)}
                        </div>
                      </div>

                      {/* Step list */}
                      <div className="space-y-6">
                        {/* Step 1: Dialing */}
                        <div className="flex gap-4 items-start">
                          {getStepStatus("dialing") === "completed" ? (
                            <div className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500 text-white shrink-0 mt-0.5">
                              <CheckCircle2 className="h-4 w-4" />
                            </div>
                          ) : (
                            <div className="flex h-6 w-6 items-center justify-center rounded-full border border-neutral-300 bg-white shrink-0 mt-0.5">
                              <div className="h-2 w-2 rounded-full bg-neutral-400" />
                            </div>
                          )}
                          <div className="space-y-0.5">
                            <h4 className={`text-[14px] font-semibold ${getStepStatus("dialing") === "completed" ? "text-emerald-600" : "text-black"}`}>
                              Dialing
                            </h4>
                            <p className="text-[11px] font-[330] text-neutral-400 leading-normal">
                              Placing call via provider
                            </p>
                          </div>
                        </div>

                        {/* Step 2: Ringing */}
                        <div className="flex gap-4 items-start">
                          {getStepStatus("ringing") === "completed" ? (
                            <div className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500 text-white shrink-0 mt-0.5">
                              <CheckCircle2 className="h-4 w-4" />
                            </div>
                          ) : getStepStatus("ringing") === "active" ? (
                            <div className="flex h-6 w-6 items-center justify-center rounded-full bg-black text-white shrink-0 mt-0.5 relative">
                              <span className="absolute inline-flex h-full w-full rounded-full bg-black opacity-75 animate-ping" />
                              <div className="h-2 w-2 rounded-full bg-white z-10" />
                            </div>
                          ) : (
                            <div className="flex h-6 w-6 items-center justify-center rounded-full border border-neutral-200 bg-white shrink-0 mt-0.5">
                              <div className="h-1.5 w-1.5 rounded-full bg-neutral-200" />
                            </div>
                          )}
                          <div className="space-y-0.5">
                            <h4 className={`text-[14px] font-semibold ${getStepStatus("ringing") === "completed" ? "text-emerald-600" : getStepStatus("ringing") === "active" ? "text-black" : "text-neutral-400"}`}>
                              Ringing
                            </h4>
                            <p className="text-[11px] font-[330] text-neutral-400 leading-normal">
                              Phone is ringing
                            </p>
                          </div>
                        </div>

                        {/* Step 3: Connected */}
                        <div className="flex gap-4 items-start">
                          {getStepStatus("connected") === "completed" ? (
                            <div className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500 text-white shrink-0 mt-0.5">
                              <CheckCircle2 className="h-4 w-4" />
                            </div>
                          ) : getStepStatus("connected") === "active" ? (
                            <div className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500 text-white shrink-0 mt-0.5 relative">
                              <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-500 opacity-75 animate-ping" />
                              <div className="h-2 w-2 rounded-full bg-white z-10" />
                            </div>
                          ) : (
                            <div className="flex h-6 w-6 items-center justify-center rounded-full border border-neutral-200 bg-white shrink-0 mt-0.5">
                              <div className="h-1.5 w-1.5 rounded-full bg-neutral-200" />
                            </div>
                          )}
                          <div className="space-y-0.5">
                            <h4 className={`text-[14px] font-semibold ${getStepStatus("connected") === "completed" ? "text-emerald-600" : getStepStatus("connected") === "active" ? "text-emerald-500" : "text-neutral-400"}`}>
                              Connected
                            </h4>
                            <p className="text-[11px] font-[330] text-neutral-400 leading-normal">
                              {getStepStatus("connected") === "active" ? "Call Active" : "Waiting..."}
                            </p>
                          </div>
                        </div>

                        {/* Step 4: Completed */}
                        <div className="flex gap-4 items-start">
                          {getStepStatus("completed") === "completed" ? (
                            <div className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500 text-white shrink-0 mt-0.5">
                              <CheckCircle2 className="h-4 w-4" />
                            </div>
                          ) : (
                            <div className="flex h-6 w-6 items-center justify-center rounded-full border border-neutral-200 bg-white shrink-0 mt-0.5">
                              <div className="h-1.5 w-1.5 rounded-full bg-neutral-200" />
                            </div>
                          )}
                          <div className="space-y-0.5">
                            <h4 className={`text-[14px] font-semibold ${getStepStatus("completed") === "completed" ? "text-emerald-600" : "text-neutral-400"}`}>
                              Completed
                            </h4>
                            <p className="text-[11px] font-[330] text-neutral-400 leading-normal">
                              {getStepStatus("completed") === "completed" ? "Call ended" : "Waiting..."}
                            </p>
                          </div>
                        </div>
                      </div>
                    </div>

                    <div className="pt-4 mt-6 border-t border-[#f1f1f1] flex justify-between items-center text-[10px] font-mono text-neutral-400">
                      <span>PROVIDER STATUS</span>
                      <span className="font-semibold text-black">{callRecord?.status?.toUpperCase() || "CONNECTING"}</span>
                    </div>
                  </div>

                  {/* Right Column: Live Transcript */}
                  <div className="md:col-span-7 rounded-[20px] border border-[#e6e6e6] bg-[#fcfcfc] p-6 flex flex-col justify-between min-h-[380px]">
                    <div className="flex-1 flex flex-col">
                      <div className="flex items-center justify-between border-b border-[#f1f1f1] pb-4 mb-4">
                        <div className="flex items-center gap-2 font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-neutral-400">
                          <AudioLines className="h-4 w-4 text-neutral-400" />
                          Live Transcript
                        </div>
                        <div className="flex items-center gap-1.5">
                          {callRecord && ["ringing", "in_progress"].includes(callRecord.status) ? (
                            <>
                              <div className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
                              <span className="text-[10px] font-mono text-neutral-400 uppercase tracking-[0.16em]">
                                {callRecord.status === "in_progress" ? "Speaking..." : "Calling..."}
                              </span>
                            </>
                          ) : (
                            <>
                              <div className="h-2 w-2 rounded-full bg-neutral-300" />
                              <span className="text-[10px] font-mono text-neutral-400 uppercase tracking-[0.16em]">Idle</span>
                            </>
                          )}
                        </div>
                      </div>

                      {/* Messages scroll area */}
                      <div className="flex-1 max-h-[260px] min-h-[200px] overflow-y-auto pr-1 space-y-4 scrollbar-thin">
                        {transcriptMessages.length === 0 ? (
                          <div className="flex flex-col items-center justify-center h-full text-center space-y-3 py-12">
                            <AudioLines className="h-10 w-10 text-neutral-300 animate-pulse" />
                            <p className="text-[13px] font-[320] text-neutral-400 leading-normal max-w-[200px] mx-auto text-center">
                              No messages yet. Start speaking to begin.
                            </p>
                          </div>
                        ) : (
                          <div className="space-y-4">
                            {transcriptMessages.map((msg, idx) => {
                              const isUser = msg.role === "user";
                              const latencyObj = callRecord?.metadata?.latency_by_sequence?.[String(msg.sequence_number)];

                              return (
                                <div key={msg.id || idx} className={`flex flex-col ${isUser ? "items-end" : "items-start"} space-y-1.5`}>
                                  <div className={`flex items-start gap-2.5 max-w-[85%] ${isUser ? "flex-row-reverse" : "flex-row"}`}>
                                    <div className={`flex h-7 w-7 items-center justify-center rounded-full text-[11px] border shrink-0 ${isUser ? "bg-black text-white border-black" : "bg-[#f7f7f5] text-black border-[#e6e6e6]"}`}>
                                      {isUser ? <User className="h-3.5 w-3.5" /> : <Volume2 className="h-3.5 w-3.5" />}
                                    </div>
                                    <div className={`rounded-[18px] px-4 py-2 text-xs md:text-[13px] leading-normal ${isUser ? "bg-black text-white rounded-tr-none" : "bg-white border border-[#e6e6e6] text-black rounded-tl-none"}`}>
                                      {msg.content}
                                    </div>
                                  </div>

                                  {/* Latency statistics for assistant messages */}
                                  {!isUser && (
                                    <div className="pl-9 pr-2 flex flex-wrap items-center gap-1.5 text-[9px] font-mono text-neutral-400">
                                      {latencyObj ? (
                                        <>
                                          <span className="bg-neutral-100 rounded px-1.5 py-0.5">STT EOT: {latencyObj.stt_eot_ms}ms</span>
                                          <span className="bg-neutral-100 rounded px-1.5 py-0.5">LLM: {latencyObj.llm_first_token_ms}ms</span>
                                          <span className="bg-neutral-100 rounded px-1.5 py-0.5">TTS: {latencyObj.tts_first_byte_ms}ms</span>
                                          <span className="bg-emerald-50 text-emerald-700 font-bold rounded px-1.5 py-0.5 border border-emerald-100">
                                            Total: {latencyObj.total_perceived_ms}ms
                                          </span>
                                        </>
                                      ) : (
                                        <span className="italic flex items-center gap-1 text-[9px]">
                                          <Loader2 className="h-2.5 w-2.5 animate-spin" />
                                          Calculating response metrics...
                                        </span>
                                      )}
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>

                <DialogFooter className="w-full sm:flex-row gap-3 pt-4 border-t border-[#f1f1f1]">
                  {callRecord && ["ringing", "in_progress"].includes(callRecord.status) ? (
                    <Button
                      onClick={endCallSession}
                      disabled={isEndingCall}
                      className="w-full h-12 rounded-full bg-rose-500 hover:bg-rose-600 disabled:opacity-70 text-white text-[14px] font-medium transition-colors flex items-center justify-center gap-2 cursor-pointer shadow-xs"
                    >
                      {isEndingCall
                        ? <Loader2 className="h-4 w-4 animate-spin" />
                        : <PhoneCall className="h-4 w-4 rotate-[135deg]" />}
                      {isEndingCall ? "Ending..." : "End Session"}
                    </Button>
                  ) : (
                    <>
                      <Button
                        onClick={() => {
                          setActiveCallId(null);
                          setCallRecord(null);
                          setTranscriptMessages([]);
                          setCallTime(0);
                        }}
                        variant="outline"
                        className="flex-1 h-12 rounded-full border-[#e6e6e6] hover:bg-[#f7f7f5] text-black text-[14px] font-medium transition-colors"
                      >
                        Start New Call
                      </Button>
                      <Button
                        onClick={() => handleCloseDialog(false)}
                        className="flex-1 h-12 rounded-full bg-black hover:bg-black/90 text-white text-[14px] font-medium transition-colors"
                      >
                        Close
                      </Button>
                    </>
                  )}
                </DialogFooter>
              </div>
            ) : (
              <>
                <div className="space-y-6 py-6">
                  <div className="space-y-2">
                    <Label className="font-mono text-[10px] font-medium uppercase tracking-[0.2em] text-neutral-400">Destination Number</Label>
                    <div className="flex items-center gap-3">
                      <Select value={countryCode} onValueChange={setCountryCode}>
                        <SelectTrigger className="w-[110px] h-14 rounded-[20px] border border-neutral-200 bg-white px-4 text-[15px] font-normal text-black focus:ring-0 focus:ring-offset-0 focus:border-neutral-200 [&>svg]:opacity-65">
                          <SelectValue placeholder="+91" />
                        </SelectTrigger>
                        <SelectContent className="rounded-xl border border-neutral-100 bg-white shadow-lg text-[14px] z-50">
                          <SelectItem value="+91">IN +91</SelectItem>
                          <SelectItem value="+1">US +1</SelectItem>
                          <SelectItem value="+44">GB +44</SelectItem>
                          <SelectItem value="+971">AE +971</SelectItem>
                        </SelectContent>
                      </Select>

                      <Input
                        placeholder="5550000000"
                        value={testCallNumber}
                        className="flex-1 h-14 border-2 border-black rounded-[20px] px-5 text-[18px] font-normal text-black placeholder:text-neutral-300 focus:outline-none focus-visible:ring-0 focus-visible:border-black focus-visible:border-2"
                        onChange={(e) => { setTestCallNumber(e.target.value); setTestCallResult(null); }}
                      />
                    </div>
                  </div>
                  {testCallResult && (
                    <div className={`p-4 rounded-xl text-[14px] font-[480] flex items-center gap-3 ${testCallResult.ok ? "bg-emerald-50 text-emerald-700 border border-emerald-100" : "bg-rose-50 text-rose-700 border border-rose-100"}`}>
                      <div className={`h-2 w-2 rounded-full ${testCallResult.ok ? "bg-emerald-500" : "bg-rose-500"}`} />
                      {testCallResult.message}
                    </div>
                  )}
                </div>
                <DialogFooter className="w-full sm:flex-col">
                  <Button
                    onClick={handleTestCall}
                    disabled={testCalling || !testCallNumber.trim()}
                    className="w-full h-14 rounded-full bg-[#828282] hover:bg-[#6e6e6e] text-white text-[15px] font-[500] transition-colors flex items-center justify-center gap-2 shadow-xs cursor-pointer disabled:opacity-50"
                  >
                    {testCalling ? <Loader2 className="h-4.5 w-4.5 animate-spin" /> : <PhoneCall className="h-4.5 w-4.5" />}
                    {testCalling ? "Connecting..." : "Initiate Live Session"}
                  </Button>
                </DialogFooter>
              </>
            )}
          </DialogContent>
        </Dialog>

        <AlertDialog open={!!confirmDeleteId} onOpenChange={() => setConfirmDeleteId(null)}>
          <AlertDialogContent className="rounded-[32px] border-[#e6e6e6] p-12 bg-white shadow-2xl">
            <AlertDialogHeader className="space-y-6">
              <AlertDialogTitle className="text-[32px] font-bold tracking-tight">Confirm Termination</AlertDialogTitle>
              <AlertDialogDescription className="text-[18px] font-[330] opacity-60 leading-relaxed">
                You are about to permanently remove <strong className="text-black font-bold">{agentToDelete?.name}</strong>. All associated configurations and logs will be archived or purged.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter className="pt-12 gap-6">
              <AlertDialogCancel className="h-14 rounded-full border-[#e6e6e6] text-[18px] font-[480] px-10">Cancel</AlertDialogCancel>
              <AlertDialogAction className="h-14 rounded-full bg-red-500 text-white hover:bg-red-600 text-[18px] font-[480] px-10 border-none" onClick={() => confirmDeleteId && handleDelete(confirmDeleteId)}>
                Terminate Agent
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </div>
  );

}
