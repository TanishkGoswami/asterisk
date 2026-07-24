import { useEffect, useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Book, Save, Loader2, Bot, FlaskConical, Plus, FileText, ChevronDown, Check, Database } from "lucide-react";
import { supabase } from "@/lib/supabase";
import { useWorkspace } from "@/context/WorkspaceContext";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";

export const Route = createFileRoute(
  "/_authenticated/dashboard/knowledge-base",
)({
  component: KnowledgeBasePage,
});

const API_URL = (
  import.meta.env.VITE_API_URL || "http://localhost:8000"
).replace(/\/$/, "");

function KnowledgeBasePage() {
  const { workspaceId: contextWsId, authHeaders: contextHeaders, loading: contextLoading } = useWorkspace();
  const [agents, setAgents] = useState<any[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string>("");
  const [content, setContent] = useState("");
  const [status, setStatus] = useState("Loading agents...");
  const [isSaving, setIsSaving] = useState(false);
  const [isJustSaved, setIsJustSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [authHeaders, setAuthHeaders] = useState<Record<string, string> | null>(null);

  useEffect(() => {
    if (contextLoading) return;
    if (!contextWsId || !contextHeaders) {
      setStatus("Not authenticated.");
      return;
    }
    setWorkspaceId(contextWsId);
    setAuthHeaders(contextHeaders);

    async function load() {
      try {
        const agentsRes = await fetch(`${API_URL}/api/v1/workspaces/${contextWsId}/agents?include_context=true`, { headers: contextHeaders! });
        if (!agentsRes.ok) throw new Error("Failed to fetch agents");
        const data = await agentsRes.json();
        setAgents(data);
        setStatus(data.length === 0 ? "No agents found. Create one first." : "");
      } catch (err) {
        setStatus(`Error: ${err instanceof Error ? err.message : "Unknown error"}`);
      }
    }
    load();
  }, [contextWsId, contextHeaders, contextLoading]);

  useEffect(() => {
    if (!selectedAgentId || agents.length === 0) return;
    const agent = agents.find((a) => a.id === selectedAgentId);
    setContent(agent?.knowledge_base || "");
    setIsJustSaved(false);
    setSaveError(null);
  }, [selectedAgentId, agents]);

  async function saveKnowledgeBase() {
    if (!workspaceId || !authHeaders || !selectedAgentId) return;
    setIsSaving(true);
    setSaveError(null);
    try {
      const res = await fetch(
        `${API_URL}/api/v1/workspaces/${workspaceId}/agents/${selectedAgentId}`,
        {
          method: "PATCH",
          headers: authHeaders,
          body: JSON.stringify({ knowledge_base: content }),
        },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      setAgents((prev) =>
        prev.map((a) => a.id === selectedAgentId ? { ...a, knowledge_base: content } : a)
      );
      setIsJustSaved(true);
      toast.success("Knowledge base context saved successfully!");
      setTimeout(() => setIsJustSaved(false), 2000);
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : "Unknown error";
      setSaveError(errMsg);
      toast.error(`Save failed: ${errMsg}`);
    } finally {
      setIsSaving(false);
    }
  }

  function handleCardClick(agentId: string) {
    setSelectedAgentId(agentId);
  }

  function handleCloseDialog() {
    setSelectedAgentId("");
    setIsJustSaved(false);
    setSaveError(null);
  }

  const selectedAgent = agents.find((a) => a.id === selectedAgentId);

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-8 px-6 py-8 md:px-8 md:py-10">
      <div className="space-y-10">

        {/* Header */}
        <div className="space-y-3">
          <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-[#999999]">
            <Book className="h-3.5 w-3.5" />
            <span>Information Architecture</span>
          </div>
          <h1 className="text-4xl font-[340] tracking-[-0.03em] text-neutral-900 md:text-5xl">
            Knowledge Base
          </h1>
          <p className="max-w-2xl text-[15px] font-[330] leading-relaxed text-neutral-500">
            Configure the neural context for each persona. Select an agent to update its specific behavioral parameters and data sets.
          </p>
        </div>

        {/* Agent Grid */}
        {agents.length > 0 ? (
          <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {agents.map((agent) => {
              const isSelected = selectedAgentId === agent.id;
              const kbLength = agent.knowledge_base?.length || 0;
              const isActive = agent.status === "active";
              return (
                <button
                  key={agent.id}
                  onClick={() => handleCardClick(agent.id)}
                  className={`group relative flex flex-col justify-between rounded-[24px] border p-6 text-left transition-all duration-300 cursor-pointer shadow-sm hover:shadow-md hover:-translate-y-1
                    ${isSelected ? "border-neutral-900 bg-neutral-50/50" : "border-neutral-200/80 bg-white hover:border-neutral-400"}`}
                >
                  <div>
                    {/* Card Top */}
                    <div className="mb-6 flex items-start justify-between">
                      <div className={`flex h-12 w-12 items-center justify-center rounded-[14px] border transition-all duration-300
                        ${isSelected ? "bg-black border-black text-white shadow-sm" : "bg-neutral-50 border-neutral-200 text-neutral-800 group-hover:bg-black group-hover:border-black group-hover:text-white"}`}
                      >
                        <Bot className="h-5 w-5" />
                      </div>

                      {/* Active/Inactive Status Badge */}
                      {isActive ? (
                        <span className="flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-medium text-emerald-700 border border-emerald-100/80">
                          <span className="relative flex h-1.5 w-1.5">
                            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                            <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500"></span>
                          </span>
                          Active
                        </span>
                      ) : (
                        <span className="flex items-center gap-1.5 rounded-full bg-neutral-50 px-2.5 py-1 text-[11px] font-medium text-neutral-500 border border-neutral-150">
                          <span className="h-1.5 w-1.5 rounded-full bg-neutral-300" />
                          Inactive
                        </span>
                      )}
                    </div>

                    {/* Agent Name & Lang */}
                    <div className="space-y-2 mb-6">
                      <h3 className="text-xl font-bold tracking-tight text-neutral-900 group-hover:text-black transition-colors">{agent.name}</h3>
                      <div>
                        <Badge variant="outline" className="h-5 rounded-full border-neutral-200 bg-neutral-50/50 px-2.5 font-mono text-[9px] uppercase tracking-wider text-neutral-500">
                          {agent.language}
                        </Badge>
                      </div>
                    </div>
                  </div>

                  {/* Character count & Edit Context indicator */}
                  <div className="flex items-center justify-between border-t border-neutral-100 pt-4 mt-auto">
                    <div className="flex items-center gap-2 text-neutral-500">
                      <Database className="h-3.5 w-3.5 text-neutral-400" />
                      <span className="font-mono text-[12px] uppercase tracking-wider text-neutral-500">
                        {kbLength > 0 ? `${kbLength.toLocaleString()} chars` : "Empty Store"}
                      </span>
                    </div>
                    <span className="text-[12px] font-medium text-neutral-400 group-hover:text-black group-hover:underline transition-all">
                      Edit Context →
                    </span>
                  </div>
                </button>
              );
            })}

            {/* Empty State / Create Card */}
            <Link
              to="/dashboard/agents/new"
              search={{ agentId: undefined }}
              className="group flex min-h-[220px] flex-col items-center justify-center rounded-[24px] border-2 border-dashed border-neutral-200 bg-neutral-50/20 p-6 text-center transition-all duration-300 hover:border-neutral-900 hover:bg-neutral-50"
            >
              <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-full border border-neutral-200 bg-white transition-all duration-300 group-hover:border-black group-hover:bg-black">
                <Plus className="h-6 w-6 text-neutral-600 transition-all duration-300 group-hover:text-white" />
              </div>
              <h4 className="mb-1 text-lg font-bold text-neutral-900">New Agent</h4>
              <p className="max-w-[200px] text-sm text-neutral-400 font-light">Add a new persona to your fleet.</p>
            </Link>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center gap-6 rounded-[24px] border border-neutral-200 bg-white p-16 text-center shadow-sm">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-neutral-50 border border-neutral-100 text-neutral-300">
              <Bot className="h-7 w-7" />
            </div>
            <p className="text-[15px] font-[330] text-neutral-400 max-w-sm">{status}</p>
            <Button asChild className="h-11 rounded-xl bg-black px-8 text-sm font-medium text-white transition-all hover:bg-neutral-900 shadow-md">
              <Link to="/dashboard/agents/new" search={{ agentId: undefined }}>
                <Plus className="h-4 w-4 mr-2" />
                Create First Agent
              </Link>
            </Button>
          </div>
        )}

        {/* Dialog / Modal popup editor */}
        <Dialog open={!!selectedAgentId} onOpenChange={(open) => { if (!open) handleCloseDialog(); }}>
          <DialogContent className="sm:max-w-4xl max-h-[92vh] flex flex-col p-0 overflow-hidden rounded-[24px] border border-neutral-200 bg-white shadow-2xl">
            {selectedAgent && (
              <>
                {/* Modal Header */}
                <div className="p-6 border-b border-neutral-100 flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-neutral-50/30">
                  <div className="flex items-center gap-3.5">
                    <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-neutral-900 text-white shadow-sm">
                      <Bot className="h-6 w-6" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <DialogTitle className="text-xl font-bold tracking-tight text-neutral-950">
                          {selectedAgent.name}
                        </DialogTitle>
                        <Badge variant="outline" className="h-5 rounded-full border-neutral-200 bg-white px-2 font-mono text-[9px] uppercase tracking-wider text-neutral-500">
                          {selectedAgent.language}
                        </Badge>
                      </div>
                      <DialogDescription className="text-xs text-neutral-500 mt-0.5 font-light">
                        Edit the system knowledge and RAG context for this agent.
                      </DialogDescription>
                    </div>
                  </div>

                  <div className="flex items-center gap-3">
                    <span className="text-xs text-neutral-400 font-mono">Status:</span>
                    {selectedAgent.status === "active" ? (
                      <span className="flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-medium text-emerald-700 border border-emerald-100/80">
                        <span className="relative flex h-1.5 w-1.5">
                          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                          <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500"></span>
                        </span>
                        Active
                      </span>
                    ) : (
                      <span className="flex items-center gap-1.5 rounded-full bg-neutral-50 px-2.5 py-1 text-[11px] font-medium text-neutral-500 border border-neutral-150">
                        <span className="h-1.5 w-1.5 rounded-full bg-neutral-300" />
                        Inactive
                      </span>
                    )}
                  </div>
                </div>

                {/* Editor Textarea */}
                <div className="flex-1 p-6 overflow-y-auto min-h-[350px] max-h-[58vh] flex flex-col gap-3">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-semibold text-neutral-500 uppercase tracking-wider">
                      Neural Context Store
                    </label>
                    <span className="text-xs font-mono text-neutral-500 bg-neutral-50 px-2.5 py-0.5 rounded-md border border-neutral-200/60">
                      {content.length.toLocaleString()} characters
                    </span>
                  </div>
                  <Textarea
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                    className="flex-1 w-full min-h-[300px] border-neutral-200 rounded-xl p-4 text-[15px] leading-relaxed font-normal focus:border-black focus:ring-1 focus:ring-black/5 resize-none transition-all shadow-inner focus-visible:ring-black/5 focus-visible:border-black"
                    placeholder="Paste company information, FAQs, product details, pricing, scripts — anything this agent should know..."
                  />
                  {saveError && (
                    <span className="text-[13px] text-red-500 italic mt-1">Save failed: {saveError}</span>
                  )}
                </div>

                {/* Modal Footer */}
                <div className="p-5 border-t border-neutral-100 bg-neutral-50/30 flex flex-col sm:flex-row items-center justify-between gap-4">
                  <Button
                    asChild
                    variant="outline"
                    className="w-full sm:w-auto h-11 rounded-xl border-neutral-200 px-5 text-sm font-medium bg-white hover:bg-neutral-50"
                  >
                    <Link to="/dashboard/qa" search={{ agentId: selectedAgentId }}>
                      <FlaskConical className="h-4 w-4 mr-2 text-neutral-500" />
                      Test Live Session
                    </Link>
                  </Button>

                  <div className="flex w-full sm:w-auto items-center gap-2">
                    <Button
                      variant="ghost"
                      onClick={handleCloseDialog}
                      className="w-full sm:w-auto h-11 rounded-xl border border-transparent px-5 text-sm font-medium hover:bg-neutral-100 text-neutral-500"
                    >
                      Cancel
                    </Button>
                    <Button
                      className="w-full sm:w-auto h-11 rounded-xl px-6 bg-black text-white text-sm font-medium hover:bg-neutral-900 transition-all shadow-md shadow-black/10"
                      disabled={isSaving}
                      onClick={saveKnowledgeBase}
                    >
                      {isSaving ? (
                        <Loader2 className="h-4 w-4 animate-spin mr-2" />
                      ) : isJustSaved ? (
                        <Check className="h-4 w-4 mr-2 text-emerald-400" />
                      ) : (
                        <Save className="h-4 w-4 mr-2" />
                      )}
                      {isSaving ? "Saving..." : isJustSaved ? "Saved!" : "Save Context"}
                    </Button>
                  </div>
                </div>
              </>
            )}
              </DialogContent>
        </Dialog>

      </div >
    </div >
  );
}

