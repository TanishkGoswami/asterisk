import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { Bot, Edit2, Play, CheckCircle, Smartphone, HelpCircle } from "lucide-react";
import { toast } from "sonner";

export const Route = createFileRoute("/_authenticated/admin/agents")({
  component: AgentManager,
});

interface Agent {
  id: string;
  workspace_id: string;
  workspaces?: { name: string };
  name: string;
  language: string;
  voice_id: string;
  voice_provider: string;
  system_prompt: string;
  fallback_message: string | null;
  status: "active" | "inactive" | "training";
}

interface PhoneShort {
  id: string;
  phone_number: string;
  agent_id: string | null;
}

interface VoiceModel {
  id: string;
  name: string;
  language: string;
}

function AgentManager() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [phones, setPhones] = useState<PhoneShort[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"list" | "form" | "test">("list");
  
  // Selected agent for edit/test
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);

  // Form states
  const [name, setName] = useState("");
  const [language, setLanguage] = useState("en-US");
  const [voiceId, setVoiceId] = useState("en-US-Neural2-A");
  const [voiceProvider, setVoiceProvider] = useState("elevenlabs");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [fallbackMessage, setFallbackMessage] = useState("");
  const [status, setStatus] = useState<"active" | "inactive" | "training">("active");
  const [availableVoiceModels, setAvailableVoiceModels] = useState<VoiceModel[]>([]);
  const [loadingVoiceModels, setLoadingVoiceModels] = useState(false);

  // Test call states
  const [targetNumber, setTargetNumber] = useState("");
  const [loadingTest, setLoadingTest] = useState(false);
  const [testCmd, setTestCmd] = useState("");

  const fetchData = async () => {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const headers = { Authorization: `Bearer ${session.access_token}` };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

      // Agents
      const agentsRes = await fetch(`${apiUrl}/api/admin/agents`, { headers });
      if (!agentsRes.ok) throw new Error("Failed to load agents.");
      const agentsData = await agentsRes.json();
      setAgents(agentsData);

      // Phone numbers list
      const phoneRes = await fetch(`${apiUrl}/api/admin/did-numbers`, { headers });
      if (phoneRes.ok) {
        const phData = await phoneRes.json();
        setPhones(phData);
      }
    } catch (e: any) {
      toast.error(e.message || "Failed to load agents directory.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  // Fetch voice models when voice provider changes
  useEffect(() => {
    const fetchVoiceModels = async () => {
      if (!voiceProvider) return;
      
      setLoadingVoiceModels(true);
      try {
        const { data: { session } } = await supabase.auth.getSession();
        if (!session) return;

        const headers = { Authorization: `Bearer ${session.access_token}` };
        const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

        const res = await fetch(`${apiUrl}/api/admin/voice-models?provider=${voiceProvider}`, { headers });
        if (!res.ok) throw new Error("Failed to load voice models.");
        const data = await res.json();
        setAvailableVoiceModels(data.models || []);
      } catch (e: any) {
        console.error("Failed to load voice models:", e);
        toast.error(e.message || "Failed to load voice models.");
      } finally {
        setLoadingVoiceModels(false);
      }
    };

    fetchVoiceModels();
  }, [voiceProvider]);

  const openEdit = (agent: Agent) => {
    setSelectedAgent(agent);
    setName(agent.name);
    setLanguage(agent.language);
    setVoiceId(agent.voice_id);
    setVoiceProvider(agent.voice_provider || "elevenlabs");
    setSystemPrompt(agent.system_prompt || "");
    setFallbackMessage(agent.fallback_message || "");
    setStatus(agent.status);
    setActiveTab("form");
  };

  const handleVoiceProviderChange = (newProvider: string) => {
    setVoiceProvider(newProvider);
    // Reset voice ID when provider changes
    setVoiceId("");
  };

  const openTestCall = (agent: Agent) => {
    setSelectedAgent(agent);
    setTargetNumber("");
    setTestCmd("");
    setActiveTab("test");
  };

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedAgent) return;
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const headers = {
        Authorization: `Bearer ${session.access_token}`,
        "Content-Type": "application/json",
      };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

      const body = {
        name,
        language,
        voice_id: voiceId,
        voice_provider: voiceProvider,
        system_prompt: systemPrompt,
        fallback_message: fallbackMessage || null,
        status,
      };

      const res = await fetch(`${apiUrl}/api/admin/agents/${selectedAgent.id}`, {
        method: "PUT",
        headers,
        body: JSON.stringify(body),
      });

      if (!res.ok) throw new Error("Failed to update agent.");
      toast.success("Agent persona configured successfully.");
      setActiveTab("list");
      fetchData();
    } catch (e: any) {
      toast.error(e.message || "Failed to save agent settings.");
    }
  };

  const triggerTestCall = async () => {
    if (!selectedAgent || !targetNumber) return;
    setLoadingTest(true);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const headers = {
        Authorization: `Bearer ${session.access_token}`,
        "Content-Type": "application/json",
      };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

      const body = {
        to_number: targetNumber,
      };

      const res = await fetch(`${apiUrl}/api/v1/workspaces/${selectedAgent.workspace_id}/agents/${selectedAgent.id}/test-call`, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to initiate test call.");
      }

      const resData = await res.json();
      if (resData.command) {
        setTestCmd(resData.command);
        toast.info("Outbound call prepared. Run the command in your VPS CLI.");
      } else {
        toast.success("Test call originated successfully.");
      }
    } catch (e: any) {
      toast.error(e.message || "Call failed.");
    } finally {
      setLoadingTest(false);
    }
  };

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-black/50">
            <Bot className="h-3.5 w-3.5" />
            <span>Management</span>
          </div>
          <h1 className="text-4xl font-[340] tracking-[-0.03em] text-black">Agent Directory</h1>
          <p className="max-w-2xl text-[14px] font-[320] leading-relaxed text-black/60">
            Monitor all deployed AI agents, edit baseline system prompts, and originate test calls globally.
          </p>
        </div>
        {activeTab !== "list" && (
          <button
            onClick={() => setActiveTab("list")}
            className="flex h-10 items-center rounded-[12px] border border-[#e6e6e6] bg-white px-4 text-[13px] font-medium text-black transition hover:bg-[#f7f7f5]"
          >
            Back to List
          </button>
        )}
      </div>

      {activeTab === "list" ? (
        loading ? (
          <div className="flex h-[30vh] items-center justify-center">
            <p className="font-mono text-[12px] uppercase tracking-widest text-black/40">
              Retrieving agent records...
            </p>
          </div>
        ) : agents.length === 0 ? (
          <div className="flex h-[200px] flex-col items-center justify-center rounded-[20px] border border-dashed border-[#e6e6e6] bg-white">
            <Bot className="h-8 w-8 text-black/10 mb-2" />
            <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-black/40">
              No agents deployed
            </p>
          </div>
        ) : (
          <div className="rounded-[20px] border border-[#e6e6e6] bg-white p-6 shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-left text-[13px]">
                <thead>
                  <tr className="border-b border-[#e6e6e6] text-black/40 font-mono text-[11px]">
                    <th className="py-2.5">Agent Label</th>
                    <th className="py-2.5">Workspace</th>
                    <th className="py-2.5">Language / Voice</th>
                    <th className="py-2.5">Status</th>
                    <th className="py-2.5 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {agents.map((a) => (
                    <tr key={a.id} className="border-b border-[#e6e6e6] hover:bg-[#fcfcfb]">
                      <td className="py-4">
                        <div className="font-medium text-black">{a.name}</div>
                        <div className="text-[11px] text-black/40 font-mono">{a.id}</div>
                      </td>
                      <td className="py-4 text-black/70">{a.workspaces?.name || "Global Workspace"}</td>
                      <td className="py-4">
                        <div className="text-black/80 font-medium">{a.language}</div>
                        <div className="text-[11px] text-black/40 font-mono">{a.voice_id} ({a.voice_provider})</div>
                      </td>
                      <td className="py-4">
                        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                          a.status === "active"
                            ? "bg-green-50 text-green-700"
                            : "bg-amber-50 text-amber-700"
                        }`}>
                          {a.status.toUpperCase()}
                        </span>
                      </td>
                      <td className="py-4 text-right space-x-2">
                        <button
                          onClick={() => openEdit(a)}
                          className="inline-flex h-8 w-8 items-center justify-center rounded-[8px] border border-[#e6e6e6] hover:bg-[#f7f7f5]"
                          title="Edit Config"
                        >
                          <Edit2 className="h-3.5 w-3.5 text-black/60" />
                        </button>
                        <button
                          onClick={() => openTestCall(a)}
                          className="inline-flex h-8 w-8 items-center justify-center rounded-[8px] border border-[#dceeb1] bg-[#dceeb1]/20 hover:bg-[#dceeb1]"
                          title="Trigger Test Call"
                        >
                          <Play className="h-3 w-3 text-black/80" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )
      ) : activeTab === "form" && selectedAgent ? (
        /* Edit Agent settings form */
        <div className="max-w-2xl rounded-[20px] border border-[#e6e6e6] bg-white p-6 shadow-sm mx-auto">
          <h2 className="text-xl font-[480] text-black mb-6">Modify Agent Persona</h2>

          <form onSubmit={handleUpdate} className="space-y-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1">
                <label className="text-[11px] font-mono uppercase tracking-wider text-black/50">Agent Name</label>
                <input
                  type="text"
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full rounded-[10px] border border-[#e6e6e6] px-3 py-2 text-[13px] text-black focus:outline-none"
                />
              </div>

              <div className="space-y-1">
                <label className="text-[11px] font-mono uppercase tracking-wider text-black/50">Agent Language</label>
                <select
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                  className="w-full rounded-[10px] border border-[#e6e6e6] bg-white px-3 py-2 text-[13px] text-black focus:outline-none"
                >
                  <option value="en-US">English (US)</option>
                  <option value="hi-IN">Hindi (India)</option>
                  <option value="en-GB">English (UK)</option>
                </select>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1">
                <label className="text-[11px] font-mono uppercase tracking-wider text-black/50">Voice Model ID</label>
                {loadingVoiceModels ? (
                  <div className="w-full rounded-[10px] border border-[#e6e6e6] px-3 py-2 text-[13px] text-black/40">
                    Loading voice models...
                  </div>
                ) : availableVoiceModels.length > 0 ? (
                  <select
                    required
                    value={voiceId}
                    onChange={(e) => setVoiceId(e.target.value)}
                    className="w-full rounded-[10px] border border-[#e6e6e6] bg-white px-3 py-2 text-[13px] text-black focus:outline-none"
                  >
                    <option value="">Select a voice model</option>
                    {availableVoiceModels.map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.name} ({model.language})
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    required
                    value={voiceId}
                    onChange={(e) => setVoiceId(e.target.value)}
                    placeholder="Enter voice model ID manually"
                    className="w-full rounded-[10px] border border-[#e6e6e6] px-3 py-2 text-[13px] text-black focus:outline-none"
                  />
                )}
              </div>

              <div className="space-y-1">
                <label className="text-[11px] font-mono uppercase tracking-wider text-black/50">Voice Provider</label>
                <select
                  value={voiceProvider}
                  onChange={(e) => handleVoiceProviderChange(e.target.value)}
                  className="w-full rounded-[10px] border border-[#e6e6e6] bg-white px-3 py-2 text-[13px] text-black focus:outline-none"
                >
                  <option value="elevenlabs">ElevenLabs</option>
                  <option value="deepgram">Deepgram</option>
                  <option value="sarvam">Sarvam AI</option>
                </select>
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-[11px] font-mono uppercase tracking-wider text-black/50">System Prompt (Persona Instructions)</label>
              <textarea
                rows={6}
                required
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                className="w-full rounded-[10px] border border-[#e6e6e6] p-3 text-[13px] text-black focus:outline-none font-mono"
              />
            </div>

            <div className="space-y-1">
              <label className="text-[11px] font-mono uppercase tracking-wider text-black/50">Fallback Greeting Message</label>
              <input
                type="text"
                placeholder="e.g. Hello, I am connecting you to an agent."
                value={fallbackMessage}
                onChange={(e) => setFallbackMessage(e.target.value)}
                className="w-full rounded-[10px] border border-[#e6e6e6] px-3 py-2 text-[13px] text-black focus:outline-none"
              />
            </div>

            <div className="space-y-1">
              <label className="text-[11px] font-mono uppercase tracking-wider text-black/50">Agent Status</label>
              <select
                value={status}
                onChange={(e: any) => setStatus(e.target.value)}
                className="w-full rounded-[10px] border border-[#e6e6e6] bg-white px-3 py-2 text-[13px] text-black focus:outline-none"
              >
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
                <option value="training">Training</option>
              </select>
            </div>

            <div className="flex justify-end gap-3 pt-6 border-t border-[#e6e6e6]">
              <button
                type="button"
                onClick={() => setActiveTab("list")}
                className="rounded-[10px] border border-[#e6e6e6] px-4 py-2 text-[13px] font-medium text-black hover:bg-[#f7f7f5]"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="rounded-[10px] bg-black px-4 py-2 text-[13px] font-medium text-white hover:bg-black/90"
              >
                Save Settings
              </button>
            </div>
          </form>
        </div>
      ) : (
        /* Test Call Console */
        <div className="max-w-xl rounded-[20px] border border-[#e6e6e6] bg-white p-6 shadow-sm mx-auto space-y-6">
          <div>
            <h2 className="text-xl font-[480] text-black">Trigger Test Call</h2>
            <p className="text-[13px] text-black/60 font-[320] mt-1">
              Verify the agent <strong className="text-black">{selectedAgent?.name}</strong> using a real-time outbound call.
            </p>
          </div>

          <div className="space-y-4">
            <div className="space-y-1">
              <label className="text-[11px] font-mono uppercase tracking-wider text-black/50">Destination Number</label>
              <input
                type="text"
                placeholder="e.g. 919343418163"
                value={targetNumber}
                onChange={(e) => setTargetNumber(e.target.value)}
                className="w-full rounded-[10px] border border-[#e6e6e6] px-3 py-2 text-[13px] text-black focus:outline-none"
              />
              <span className="text-[11px] text-black/40 block mt-1">
                Enter your mobile number with country prefix but without the `+` sign.
              </span>
            </div>

            <button
              onClick={triggerTestCall}
              disabled={loadingTest || !targetNumber}
              className="w-full flex h-10 items-center justify-center rounded-[10px] bg-black text-[13px] font-medium text-white transition hover:bg-black/90 disabled:opacity-50"
            >
              {loadingTest ? "Originating..." : "Start Outbound Call"}
            </button>

            {testCmd && (
              <div className="rounded-[12px] border border-amber-200 bg-amber-50 p-4 space-y-2">
                <span className="font-mono text-[10px] uppercase tracking-wider text-amber-800 font-bold block">
                  Manual Command Required
                </span>
                <p className="text-[12px] text-amber-900/80 leading-relaxed font-[320]">
                  Your local environment is not running with automatic SSH keys. 
                  Please run the following command directly inside your remote VPS shell terminal to start dialing:
                </p>
                <pre className="rounded-[8px] bg-black/5 p-2.5 font-mono text-[11px] text-black border border-amber-200/40 select-all whitespace-pre-wrap">
                  {testCmd}
                </pre>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
