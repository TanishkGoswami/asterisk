import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { RefreshCw, Play, Square, Layers, List, PhoneCall, Check, AlertCircle } from "lucide-react";
import { toast } from "sonner";

export const Route = createFileRoute("/_authenticated/admin/batch-calls")({
  component: BatchCallsManager,
});

interface BatchRun {
  id: string;
  workspace_id: string;
  agent_id: string;
  status: string;
  total_numbers: number;
  queued_count: number;
  dialed_count: number;
  connected_count: number;
  failed_count: number;
  rejected_count: number;
  cac_rejected_count: number;
  completed_count?: number;
  retry_count?: number;
  started_at: string | null;
  ended_at: string | null;
  created_at: string;
  workspaces?: { name: string };
  agents?: { name: string };
}

interface BatchItem {
  id: string;
  phone_number: string;
  status: string;
  call_uuid: string | null;
  failure_reason: string | null;
  rejection_reason: string | null;
  attempt_count?: number;
  next_attempt_at?: string | null;
  last_cac_reason?: string | null;
  started_at: string | null;
  ended_at: string | null;
}

interface Workspace {
  id: string;
  name: string;
}

interface Agent {
  id: string;
  name: string;
}

function BatchCallsManager() {
  const [runs, setRuns] = useState<BatchRun[]>([]);
  const [selectedRun, setSelectedRun] = useState<BatchRun | null>(null);
  const [items, setItems] = useState<BatchItem[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  
  // Creation state
  const [selectedWs, setSelectedWs] = useState("");
  const [selectedAgent, setSelectedAgent] = useState("");
  const [numbersText, setNumbersText] = useState("");
  const [maxParallel, setMaxParallel] = useState(1);
  const [dryRun, setDryRun] = useState(true); // Default to dry-run validation for safety!
  const [confirmReal, setConfirmReal] = useState(false);
  const [safetyStatus, setSafetyStatus] = useState<any>(null);

  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [page, setPage] = useState(1);
  const [itemPage, setItemPage] = useState(1);

  const fetchSafetyStatus = async () => {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;
      const headers = { Authorization: `Bearer ${session.access_token}` };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";
      const res = await fetch(`${apiUrl}/api/admin/outbound-safety/status`, { headers });
      if (res.ok) {
        const data = await res.json();
        setSafetyStatus(data);
      }
    } catch (err) {
      console.error("Error loading safety status:", err);
    }
  };

  const fetchCampaigns = async () => {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const headers = { Authorization: `Bearer ${session.access_token}` };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

      const res = await fetch(`${apiUrl}/api/admin/batch-calls?limit=10&page=${page}`, { headers });
      if (!res.ok) throw new Error("Failed to load campaigns.");
      const data = await res.json();
      setRuns(data);
      
      if (data.length > 0 && !selectedRun) {
        setSelectedRun(data[0]);
        fetchRunDetails(data[0].id);
      }
    } catch (e: any) {
      toast.error(e.message || "Failed to load campaigns.");
    } finally {
      setLoading(false);
    }
  };

  const fetchRunDetails = async (runId: string) => {
    setDetailLoading(true);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const headers = { Authorization: `Bearer ${session.access_token}` };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

      // 1. Fetch updated run stats
      const runRes = await fetch(`${apiUrl}/api/admin/batch-calls/${runId}`, { headers });
      if (runRes.ok) {
        const runData = await runRes.json();
        setSelectedRun(runData);
      }

      // 2. Fetch paginated campaign items
      const itemsRes = await fetch(`${apiUrl}/api/admin/batch-calls/${runId}/items?limit=50&page=${itemPage}`, { headers });
      if (itemsRes.ok) {
        const itemsData = await itemsRes.json();
        setItems(itemsData);
      }
    } catch (e: any) {
      toast.error("Failed to load campaign numbers details.");
    } finally {
      setDetailLoading(false);
    }
  };

  const handleStartCampaign = async () => {
    if (!selectedWs || !selectedAgent || !numbersText.trim()) {
      toast.error("Please fill in all campaign parameters.");
      return;
    }

    const numbers = numbersText
      .split(/[\n,]/)
      .map((num) => num.trim())
      .filter((num) => num.length >= 7);

    if (numbers.length === 0) {
      toast.error("Please input valid phone numbers.");
      return;
    }

    setSubmitting(true);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const headers = { 
        Authorization: `Bearer ${session.access_token}`,
        "Content-Type": "application/json"
      };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

      const res = await fetch(`${apiUrl}/api/admin/batch-calls`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          workspace_id: selectedWs,
          agent_id: selectedAgent,
          phone_numbers: numbers,
          max_parallel_calls: maxParallel,
          dry_run: dryRun,
          confirm_real_dialing: confirmReal
        })
      });

      if (!res.ok) throw new Error("Failed to start dialing campaign.");
      
      toast.success(`Dialing campaign started with ${numbers.length} numbers.`);
      setNumbersText("");
      fetchCampaigns();
    } catch (e: any) {
      toast.error(e.message || "Error starting campaign.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleStopCampaign = async (runId: string) => {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const headers = { Authorization: `Bearer ${session.access_token}` };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

      const res = await fetch(`${apiUrl}/api/admin/batch-calls/${runId}/stop`, {
        method: "POST",
        headers
      });

      if (!res.ok) throw new Error("Failed to stop campaign.");
      
      toast.success("Dialing campaign stopped/cancelled.");
      fetchCampaigns();
      if (selectedRun && selectedRun.id === runId) {
        fetchRunDetails(runId);
      }
    } catch (e: any) {
      toast.error(e.message || "Error stopping campaign.");
    }
  };

  const handlePauseCampaign = async (runId: string) => {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const headers = { Authorization: `Bearer ${session.access_token}` };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

      const res = await fetch(`${apiUrl}/api/admin/batch-calls/${runId}/pause`, {
        method: "POST",
        headers
      });

      if (!res.ok) throw new Error("Failed to pause campaign.");
      
      toast.success("Campaign paused successfully.");
      fetchCampaigns();
      if (selectedRun && selectedRun.id === runId) {
        fetchRunDetails(runId);
      }
    } catch (e: any) {
      toast.error(e.message || "Error pausing campaign.");
    }
  };

  const handleResumeCampaign = async (runId: string) => {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const headers = { Authorization: `Bearer ${session.access_token}` };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

      const res = await fetch(`${apiUrl}/api/admin/batch-calls/${runId}/resume`, {
        method: "POST",
        headers: {
          ...headers,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          confirm_real_dialing: true
        })
      });

      if (!res.ok) throw new Error("Failed to resume campaign.");
      
      toast.success("Campaign resumed successfully.");
      fetchCampaigns();
      if (selectedRun && selectedRun.id === runId) {
        fetchRunDetails(runId);
      }
    } catch (e: any) {
      toast.error(e.message || "Error resuming campaign.");
    }
  };

  const fetchFormMetadata = async () => {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;
      const headers = { Authorization: `Bearer ${session.access_token}` };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

      const wsRes = await fetch(`${apiUrl}/api/admin/workspaces`, { headers });
      if (wsRes.ok) {
        const wsData = await wsRes.json();
        setWorkspaces(wsData || []);
        if (wsData && wsData.length > 0) {
          setSelectedWs(wsData[0].id);
        }
      }
    } catch (err) {
      console.error("Error loading workspaces metadata:", err);
    }
  };

  useEffect(() => {
    fetchFormMetadata();
    fetchSafetyStatus();
  }, []);

  useEffect(() => {
    if (!selectedWs) {
      setAgents([]);
      return;
    }

    const fetchAgentsForWorkspace = async () => {
      try {
        const { data: { session } } = await supabase.auth.getSession();
        if (!session) return;
        const headers = { Authorization: `Bearer ${session.access_token}` };
        const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

        const res = await fetch(`${apiUrl}/api/v1/workspaces/${selectedWs}/agents`, { headers });
        if (res.ok) {
          const data = await res.json();
          setAgents(data || []);
          if (data && data.length > 0) {
            setSelectedAgent(data[0].id);
          } else {
            setSelectedAgent("");
          }
        }
      } catch (err) {
        console.error("Error loading agents for workspace:", err);
      }
    };

    fetchAgentsForWorkspace();
  }, [selectedWs]);

  useEffect(() => {
    fetchCampaigns();
  }, [page]);

  useEffect(() => {
    if (selectedRun) {
      fetchRunDetails(selectedRun.id);
    }
  }, [itemPage]);

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-black/50">
            <PhoneCall className="h-3.5 w-3.5" />
            <span>Outbound Marketing</span>
          </div>
          <h1 className="text-4xl font-[340] tracking-[-0.03em] text-black">Batch Dial campaigns</h1>
          <p className="max-w-2xl text-[14px] font-[320] leading-relaxed text-black/60">
            Deploy bulk voice dial campaigns sequentially under Call Admission limits to avoid trunk blockages.
          </p>
        </div>
        <button
          onClick={fetchCampaigns}
          className="flex h-10 w-10 items-center justify-center rounded-[12px] border border-[#e6e6e6] bg-white transition hover:bg-[#f7f7f5]"
        >
          <RefreshCw className="h-4 w-4 text-black/60" />
        </button>
      </div>

      {/* Outbound Safety Status Banner */}
      {safetyStatus && (
        <div className={`p-4 rounded-[16px] border ${
          safetyStatus.switches?.OUTBOUND_CALLS_ENABLED && safetyStatus.switches?.REAL_DIALING_ENABLED
            ? "border-green-100 bg-green-50/50 text-green-900"
            : "border-red-100 bg-red-50/50 text-red-900"
        } flex items-start gap-3 text-left text-[13px]`}>
          <AlertCircle className={`h-5 w-5 shrink-0 ${
            safetyStatus.switches?.OUTBOUND_CALLS_ENABLED && safetyStatus.switches?.REAL_DIALING_ENABLED
              ? "text-green-600"
              : "text-red-600"
          }`} />
          <div className="flex-1 space-y-1">
            <p className="font-medium">
              Telephony Safety Gate: {
                safetyStatus.switches?.OUTBOUND_CALLS_ENABLED && safetyStatus.switches?.REAL_DIALING_ENABLED
                  ? "Operational & Protected"
                  : "Outbound Dialing Globally Suspended"
              }
            </p>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] opacity-75 font-mono">
              <span>OUTBOUND_CALLS: {safetyStatus.switches?.OUTBOUND_CALLS_ENABLED ? "ENABLED" : "DISABLED"}</span>
              <span>BATCH_CALLS: {safetyStatus.switches?.BATCH_CALLS_ENABLED ? "ENABLED" : "DISABLED"}</span>
              <span>REAL_DIALING: {safetyStatus.switches?.REAL_DIALING_ENABLED ? "ENABLED" : "DISABLED"}</span>
              <span>TRUNK_PROVIDER: {safetyStatus.switches?.TWILIO_SIP_TRUNK_ENABLED ? "ENABLED" : "DISABLED"}</span>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex h-[40vh] items-center justify-center">
          <p className="font-mono text-[12px] uppercase tracking-widest text-black/40">
            Retrieving campaign queues...
          </p>
        </div>
      ) : (
        <div className="grid gap-8 lg:grid-cols-3">
          {/* Left: Campaign Wizard & History list */}
          <div className="space-y-6">
            {/* Creator Wizard */}
            <div className="rounded-[20px] border border-[#e6e6e6] bg-white p-5 shadow-sm space-y-4">
              <h2 className="text-[15px] font-[340] text-black border-b border-[#e6e6e6] pb-3 flex items-center gap-2">
                <Play className="h-4 w-4 text-black/50" />
                <span>Launch New Campaign</span>
              </h2>

              <div className="space-y-4 text-left">
                <div>
                  <label className="text-[11px] font-mono uppercase text-black/40 block mb-1.5">
                    Target Workspace
                  </label>
                  <select
                    value={selectedWs}
                    onChange={(e) => setSelectedWs(e.target.value)}
                    className="w-full h-10 px-3 rounded-[10px] border border-[#e6e6e6] bg-white text-[13px] text-black focus:outline-none"
                  >
                    {workspaces.map((ws) => (
                      <option key={ws.id} value={ws.id}>
                        {ws.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="text-[11px] font-mono uppercase text-black/40 block mb-1.5">
                    Agent Voice Assistant
                  </label>
                  <select
                    value={selectedAgent}
                    onChange={(e) => setSelectedAgent(e.target.value)}
                    className="w-full h-10 px-3 rounded-[10px] border border-[#e6e6e6] bg-white text-[13px] text-black focus:outline-none"
                  >
                    {agents.map((ag) => (
                      <option key={ag.id} value={ag.id}>
                        {ag.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="text-[11px] font-mono uppercase text-black/40 block mb-1.5">
                    Max Parallel Calls
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={10}
                    value={maxParallel}
                    onChange={(e) => setMaxParallel(parseInt(e.target.value) || 1)}
                    className="w-full h-10 px-3 rounded-[10px] border border-[#e6e6e6] bg-white text-[13px] text-black focus:outline-none"
                  />
                </div>

                <div>
                  <label className="text-[11px] font-mono uppercase text-black/40 block mb-1.5">
                    Target Numbers (Comma/Newline separated)
                  </label>
                  <textarea
                    value={numbersText}
                    onChange={(e) => setNumbersText(e.target.value)}
                    placeholder="+1234567890&#10;+1987654321"
                    rows={4}
                    className="w-full p-3 rounded-[10px] border border-[#e6e6e6] bg-white text-[13px] text-black focus:outline-none font-mono"
                  />
                </div>

                {/* Dry Run / Real Dialing Safety Controls */}
                <div className="p-3.5 rounded-[12px] border border-[#e6e6e6] bg-[#fcfcfb] space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex flex-col text-left">
                      <span className="text-[12px] font-medium text-black">Dry Run Validation</span>
                      <span className="text-[10px] text-black/50">Verify safety rules without dialing</span>
                    </div>
                    <input
                      type="checkbox"
                      checked={dryRun}
                      onChange={(e) => {
                        setDryRun(e.target.checked);
                        if (e.target.checked) setConfirmReal(false);
                      }}
                      className="h-4 w-4 rounded border-gray-300 text-black focus:ring-black"
                    />
                  </div>

                  {!dryRun && (
                    <div className="space-y-3 pt-2 border-t border-[#e6e6e6]">
                      <div className="flex items-start gap-2 text-left bg-amber-50/50 border border-amber-100 p-2.5 rounded-[8px] text-[11px] text-amber-800">
                        <AlertCircle className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
                        <p>
                          <strong>Real Dialing Mode Active:</strong> This campaign will place live outbound calls via Twilio. Telephony charges will apply.
                        </p>
                      </div>
                      <div className="flex items-center gap-2 text-left">
                        <input
                          type="checkbox"
                          checked={confirmReal}
                          onChange={(e) => setConfirmReal(e.target.checked)}
                          id="confirm-real-checkbox"
                          className="h-4 w-4 rounded border-gray-300 text-black focus:ring-black"
                        />
                        <label htmlFor="confirm-real-checkbox" className="text-[11px] text-black/70 cursor-pointer select-none">
                          I confirm I want to initiate real calls.
                        </label>
                      </div>
                    </div>
                  )}
                </div>

                <button
                  onClick={handleStartCampaign}
                  disabled={submitting || (!dryRun && !confirmReal)}
                  className="w-full h-11 bg-black text-white rounded-[12px] text-[13px] font-medium transition hover:bg-black/90 disabled:opacity-60 flex items-center justify-center gap-2"
                >
                  {submitting ? "Deploying Campaign..." : dryRun ? "Start Dry-Run Campaign" : "Start Live Campaign"}
                </button>
              </div>
            </div>

            {/* Runs list */}
            <div className="rounded-[20px] border border-[#e6e6e6] bg-white p-5 shadow-sm space-y-4 max-h-[400px] overflow-y-auto">
              <h2 className="text-[15px] font-[340] text-black border-b border-[#e6e6e6] pb-3 flex items-center gap-2">
                <List className="h-4 w-4 text-black/50" />
                <span>Campaign History</span>
              </h2>

              <div className="space-y-3">
                {runs.map((run) => (
                  <div
                    key={run.id}
                    onClick={() => {
                      setSelectedRun(run);
                      fetchRunDetails(run.id);
                    }}
                    className={`p-4 rounded-[14px] border transition cursor-pointer text-left ${
                      selectedRun?.id === run.id
                        ? "border-black bg-[#fcfcfb]"
                        : "border-[#e6e6e6] bg-white hover:bg-[#fafaf9]"
                    }`}
                  >
                    <div className="flex justify-between items-center mb-1">
                      <span className="text-[13px] font-bold text-black capitalize">
                        {run.agents?.name || "AI Agent Dial"}
                      </span>
                      <span className={`rounded-full px-2 py-0.5 text-[9px] font-bold uppercase ${
                        run.status === "completed" 
                          ? "bg-green-50 text-green-700" 
                          : run.status === "running"
                            ? "bg-blue-50 text-blue-700"
                            : run.status === "paused"
                              ? "bg-amber-50 text-amber-700"
                              : run.status === "cancelled" || run.status === "stopped"
                                ? "bg-gray-100 text-gray-700"
                                : "bg-red-50 text-red-700"
                      }`}>
                        {run.status}
                      </span>
                    </div>
                    <p className="text-[11px] text-black/50 font-mono">
                      Queue: {run.dialed_count}/{run.total_numbers} dialed
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Right: Dialing progress details */}
          <div className="lg:col-span-2">
            {detailLoading || !selectedRun ? (
              <div className="rounded-[20px] border border-[#e6e6e6] bg-white p-12 text-center shadow-sm">
                <p className="font-mono text-[12px] text-black/40 uppercase tracking-widest">
                  Loading Dialing progress details...
                </p>
              </div>
            ) : (
              <div className="rounded-[20px] border border-[#e6e6e6] bg-white p-6 shadow-sm space-y-6">
                <div className="flex justify-between items-center border-b border-[#e6e6e6] pb-4">
                  <div>
                    <h2 className="text-[18px] font-[340] text-black capitalize">
                      {selectedRun.agents?.name || "Dialing Campaign"} details
                    </h2>
                    <p className="text-[12px] text-black/50 font-mono mt-0.5">
                      Created on: {new Date(selectedRun.created_at).toLocaleString()}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    {selectedRun.status === "running" && (
                      <>
                        <button
                          onClick={() => handlePauseCampaign(selectedRun.id)}
                          className="h-9 px-3.5 bg-amber-50 border border-amber-200 text-amber-700 rounded-[8px] text-[12px] font-semibold transition hover:bg-amber-100 flex items-center gap-1.5"
                        >
                          <span>Pause</span>
                        </button>
                        <button
                          onClick={() => handleStopCampaign(selectedRun.id)}
                          className="h-9 px-3.5 bg-red-50 border border-red-200 text-red-700 rounded-[8px] text-[12px] font-semibold transition hover:bg-red-100 flex items-center gap-1.5"
                        >
                          <Square className="h-3.5 w-3.5" />
                          <span>Abort</span>
                        </button>
                      </>
                    )}
                    {selectedRun.status === "paused" && (
                      <>
                        <button
                          onClick={() => handleResumeCampaign(selectedRun.id)}
                          className="h-9 px-3.5 bg-green-50 border border-green-200 text-green-700 rounded-[8px] text-[12px] font-semibold transition hover:bg-green-100 flex items-center gap-1.5"
                        >
                          <Play className="h-3.5 w-3.5" />
                          <span>Resume</span>
                        </button>
                        <button
                          onClick={() => handleStopCampaign(selectedRun.id)}
                          className="h-9 px-3.5 bg-red-50 border border-red-200 text-red-700 rounded-[8px] text-[12px] font-semibold transition hover:bg-red-100 flex items-center gap-1.5"
                        >
                          <Square className="h-3.5 w-3.5" />
                          <span>Abort</span>
                        </button>
                      </>
                    )}
                  </div>
                </div>

                {/* Counters Grid */}
                <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                  <div className="p-3 bg-[#fcfcfb] border border-[#e6e6e6] rounded-[12px]">
                    <span className="text-[10px] font-mono uppercase text-black/40">Total numbers</span>
                    <p className="text-[20px] font-semibold text-black mt-0.5">{selectedRun.total_numbers}</p>
                  </div>
                  <div className="p-3 bg-[#fcfcfb] border border-[#e6e6e6] rounded-[12px]">
                    <span className="text-[10px] font-mono uppercase text-black/40">Completed</span>
                    <p className="text-[20px] font-semibold text-green-600 mt-0.5">{selectedRun.completed_count ?? selectedRun.connected_count}</p>
                  </div>
                  <div className="p-3 bg-[#fcfcfb] border border-[#e6e6e6] rounded-[12px]">
                    <span className="text-[10px] font-mono uppercase text-black/40">Retry Later</span>
                    <p className="text-[20px] font-semibold text-purple-600 mt-0.5">{selectedRun.retry_count ?? 0}</p>
                  </div>
                  <div className="p-3 bg-[#fcfcfb] border border-[#e6e6e6] rounded-[12px]">
                    <span className="text-[10px] font-mono uppercase text-black/40">Failed</span>
                    <p className="text-[20px] font-semibold text-red-500 mt-0.5">{selectedRun.failed_count}</p>
                  </div>
                  <div className="p-3 bg-[#fcfcfb] border border-[#e6e6e6] rounded-[12px]">
                    <span className="text-[10px] font-mono uppercase text-black/40">CAC/Invalid</span>
                    <p className="text-[20px] font-semibold text-amber-600 mt-0.5">{(selectedRun.cac_rejected_count || 0) + (selectedRun.rejected_count || 0)}</p>
                  </div>
                </div>

                {/* Numbers Status Table */}
                <div className="space-y-4">
                  <h3 className="text-[14px] font-[340] text-black">Dialed Numbers list</h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-[13px]">
                      <thead>
                        <tr className="border-b border-[#e6e6e6] text-black/40 font-mono text-[10px] uppercase">
                          <th className="py-2">Phone Number</th>
                          <th className="py-2">Status</th>
                          <th className="py-2">UUID</th>
                          <th className="py-2">Attempts</th>
                          <th className="py-2">Next Dial</th>
                          <th className="py-2 text-right">Error / Reason</th>
                        </tr>
                      </thead>
                      <tbody>
                        {items.map((it) => (
                          <tr key={it.id} className="border-b border-[#f2f2f0]">
                            <td className="py-2.5 font-mono text-[12px] text-black">
                              {it.phone_number}
                            </td>
                            <td className="py-2.5">
                              <span className={`rounded-full px-2 py-0.5 text-[9px] font-bold uppercase ${
                                it.status === "completed"
                                  ? "bg-green-50 text-green-700"
                                  : it.status === "dialing" || it.status === "connected"
                                    ? "bg-blue-50 text-blue-700"
                                    : it.status === "retry_later"
                                      ? "bg-purple-50 text-purple-700"
                                      : it.status === "cac_rejected"
                                        ? "bg-amber-50 text-amber-700"
                                        : it.status === "invalid_number"
                                          ? "bg-gray-100 text-gray-700"
                                          : it.status === "cancelled"
                                            ? "bg-gray-50 text-gray-500"
                                            : "bg-red-50 text-red-700"
                              }`}>
                                {it.status}
                              </span>
                            </td>
                            <td className="py-2.5 font-mono text-[11px] text-black/50">
                              {it.call_uuid ? it.call_uuid.substring(0, 15) + "..." : "-"}
                            </td>
                            <td className="py-2.5 font-mono text-[11px] text-black/50">
                              {it.attempt_count ?? 0}
                            </td>
                            <td className="py-2.5 font-mono text-[11px] text-black/50">
                              {it.next_attempt_at ? new Date(it.next_attempt_at).toLocaleTimeString() : "-"}
                            </td>
                            <td className="py-2.5 text-right font-mono text-[11px] text-black/60">
                              {it.last_cac_reason || it.rejection_reason || it.failure_reason || "-"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {/* Pagination */}
                  <div className="flex justify-between items-center pt-3 border-t border-[#e6e6e6]">
                    <button
                      disabled={itemPage <= 1}
                      onClick={() => setItemPage(itemPage - 1)}
                      className="px-3.5 py-1.5 rounded-[8px] border border-[#e6e6e6] text-[12px] bg-white hover:bg-[#fcfcfb] disabled:opacity-50"
                    >
                      Previous
                    </button>
                    <span className="text-[12px] text-black/60">Page {itemPage}</span>
                    <button
                      disabled={items.length < 50}
                      onClick={() => setItemPage(itemPage + 1)}
                      className="px-3.5 py-1.5 rounded-[8px] border border-[#e6e6e6] text-[12px] bg-white hover:bg-[#fcfcfb] disabled:opacity-50"
                    >
                      Next
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
