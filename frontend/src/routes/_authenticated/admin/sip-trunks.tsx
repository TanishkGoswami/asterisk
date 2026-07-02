import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { AudioLines, Plus, Edit2, Trash2, CheckCircle, AlertTriangle, RefreshCw, Eye, EyeOff, Copy, Check } from "lucide-react";
import { toast } from "sonner";
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

export const Route = createFileRoute("/_authenticated/admin/sip-trunks")({
  component: SIPTrunkManager,
});

interface SIPTrunk {
  id: string;
  workspace_id: string;
  workspaces?: { name: string };
  name: string;
  provider_type: string;
  auth_type: "ip_auth" | "username_password";
  sip_proxy: string;
  sip_port: number;
  transport: "udp" | "tcp" | "tls";
  username?: string;
  password?: string;
  outbound_caller_id?: string;
  provider_ips?: string[];
  allowed_codecs: string[];
  max_concurrent_calls: number;
  status: string;
}

interface WorkspaceShort {
  id: string;
  name: string;
}

function SIPTrunkManager() {
  const [trunks, setTrunks] = useState<SIPTrunk[]>([]);
  const [workspaces, setWorkspaces] = useState<WorkspaceShort[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"list" | "form">("list");
  
  // Registration output
  const [regOutput, setRegOutput] = useState("");
  const [loadingReg, setLoadingReg] = useState(false);

  // Selected Trunk Config states
  const [selectedTrunkId, setSelectedTrunkId] = useState<string | null>(null);
  const [generatedConfig, setGeneratedConfig] = useState<{ pjsip_conf: string; extensions_conf: string } | null>(null);
  const [loadingConfig, setLoadingConfig] = useState(false);
  const [copiedField, setCopiedField] = useState<'pjsip' | 'ext' | null>(null);

  // Form states
  const [editId, setEditId] = useState<string | null>(null);
  const [workspaceId, setWorkspaceId] = useState("");
  const [name, setName] = useState("");
  const [providerType, setProviderType] = useState("custom");
  const [authType, setAuthType] = useState<"ip_auth" | "username_password">("username_password");
  const [sipProxy, setSipProxy] = useState("");
  const [sipPort, setSipPort] = useState(5060);
  const [transport, setTransport] = useState<"udp" | "tcp" | "tls">("udp");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [outboundCallerId, setOutboundCallerId] = useState("");
  const [providerIps, setProviderIps] = useState("");
  const [codecs, setCodecs] = useState<string[]>(["ulaw", "alaw"]);
  const [maxCalls, setMaxCalls] = useState(10);

  // Confirmations
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [reloadOpen, setReloadOpen] = useState(false);

  const fetchTrunksAndWorkspaces = async () => {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const headers = { Authorization: `Bearer ${session.access_token}` };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

      // Trunks
      const trunksRes = await fetch(`${apiUrl}/api/admin/sip-trunks`, { headers });
      if (!trunksRes.ok) throw new Error("Failed to load SIP trunks.");
      const trunksData = await trunksRes.json();
      setTrunks(trunksData);

      // Workspaces
      const workspacesRes = await fetch(`${apiUrl}/api/admin/workspaces`, { headers });
      if (workspacesRes.ok) {
        const wsData = await workspacesRes.json();
        setWorkspaces(wsData);
        if (wsData.length > 0 && !workspaceId) {
          setWorkspaceId(wsData[0].id);
        }
      }
    } catch (e: any) {
      toast.error(e.message || "Failed to load SIP modules.");
    } finally {
      setLoading(false);
    }
  };

  const fetchRegistrations = async () => {
    setLoadingReg(true);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const headers = { Authorization: `Bearer ${session.access_token}` };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

      const res = await fetch(`${apiUrl}/api/admin/sip-trunks/registrations`, { headers });
      if (res.ok) {
        const data = await res.json();
        setRegOutput(data.raw_output || "No registration output returned.");
      }
    } catch (e: any) {
      toast.error("Failed to query registrations.");
    } finally {
      setLoadingReg(false);
    }
  };

  const fetchConfig = async (trunkId: string) => {
    setLoadingConfig(true);
    setSelectedTrunkId(trunkId);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const headers = { Authorization: `Bearer ${session.access_token}` };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

      const res = await fetch(`${apiUrl}/api/admin/sip-trunks/${trunkId}/generate-config`, {
        method: "POST",
        headers
      });
      if (res.ok) {
        const data = await res.json();
        setGeneratedConfig(data);
      } else {
        setGeneratedConfig(null);
      }
    } catch (e) {
      toast.error("Failed to generate configuration.");
      setGeneratedConfig(null);
    } finally {
      setLoadingConfig(false);
    }
  };

  const handleCopy = (text: string, type: 'pjsip' | 'ext') => {
    navigator.clipboard.writeText(text);
    setCopiedField(type);
    setTimeout(() => setCopiedField(null), 2000);
    toast.success("Configuration copied to clipboard");
  };

  useEffect(() => {
    fetchTrunksAndWorkspaces();
    fetchRegistrations();
  }, []);

  const openCreateForm = () => {
    setEditId(null);
    setName("");
    setProviderType("custom");
    setAuthType("username_password");
    setSipProxy("");
    setSipPort(5060);
    setTransport("udp");
    setUsername("");
    setPassword("");
    setOutboundCallerId("");
    setProviderIps("");
    setCodecs(["ulaw", "alaw"]);
    setMaxCalls(10);
    setActiveTab("form");
  };

  const openEditForm = (trunk: SIPTrunk) => {
    setEditId(trunk.id);
    setWorkspaceId(trunk.workspace_id);
    setName(trunk.name);
    setProviderType(trunk.provider_type);
    setAuthType(trunk.auth_type);
    setSipProxy(trunk.sip_proxy);
    setSipPort(trunk.sip_port);
    setTransport(trunk.transport);
    setUsername(trunk.username || "");
    setPassword("");
    setOutboundCallerId(trunk.outbound_caller_id || "");
    setProviderIps(trunk.provider_ips ? trunk.provider_ips.join(", ") : "");
    setCodecs(trunk.allowed_codecs || ["ulaw", "alaw"]);
    setMaxCalls(trunk.max_concurrent_calls);
    setActiveTab("form");
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const headers = {
        Authorization: `Bearer ${session.access_token}`,
        "Content-Type": "application/json",
      };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

      const ipList = providerIps
        .split(",")
        .map((ip) => ip.trim())
        .filter((ip) => ip !== "");

      const body = {
        workspace_id: workspaceId,
        name,
        provider_type: providerType,
        auth_type: authType,
        sip_proxy: sipProxy,
        sip_port: sipPort,
        transport,
        username: authType === "username_password" ? username : null,
        password: authType === "username_password" && password ? password : null,
        outbound_caller_id: outboundCallerId || null,
        provider_ips: authType === "ip_auth" ? ipList : [],
        allowed_codecs: codecs,
        max_concurrent_calls: maxCalls,
      };

      const url = editId
        ? `${apiUrl}/api/admin/sip-trunks/${editId}`
        : `${apiUrl}/api/admin/sip-trunks`;

      const method = editId ? "PUT" : "POST";

      const res = await fetch(url, {
        method,
        headers,
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to save SIP trunk.");
      }

      toast.success(editId ? "SIP Trunk updated." : "SIP Trunk created.");
      setActiveTab("list");
      fetchTrunksAndWorkspaces();
      fetchRegistrations();
    } catch (e: any) {
      toast.error(e.message || "Failed to save SIP trunk.");
    }
  };

  const confirmDelete = (id: string) => {
    setDeleteId(id);
    setDeleteOpen(true);
  };

  const handleDelete = async () => {
    if (!deleteId) return;
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const headers = { Authorization: `Bearer ${session.access_token}` };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

      const res = await fetch(`${apiUrl}/api/admin/sip-trunks/${deleteId}`, {
        method: "DELETE",
        headers,
      });

      if (!res.ok) throw new Error("Failed to delete trunk.");
      toast.success("SIP Trunk deleted.");
      setDeleteOpen(false);
      fetchTrunksAndWorkspaces();
      fetchRegistrations();
    } catch (e: any) {
      toast.error(e.message || "Failed to delete trunk.");
    }
  };

  const handleReload = async () => {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const headers = { Authorization: `Bearer ${session.access_token}` };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

      const res = await fetch(`${apiUrl}/api/admin/sip-trunks/reload-asterisk`, {
        method: "POST",
        headers,
      });

      if (!res.ok) throw new Error("Failed to reload Asterisk.");
      toast.success("Asterisk configurations reloaded.");
      setReloadOpen(false);
      fetchRegistrations();
    } catch (e: any) {
      toast.error(e.message || "Reload failed.");
    }
  };

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-black/50">
            <AudioLines className="h-3.5 w-3.5" />
            <span>Telephony</span>
          </div>
          <h1 className="text-4xl font-[340] tracking-[-0.03em] text-black">SIP Trunks</h1>
          <p className="max-w-2xl text-[14px] font-[320] leading-relaxed text-black/60">
            Configure SIP gateways, manage IP and Credential registrations, and trigger Asterisk PJSIP configuration reloads.
          </p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => setReloadOpen(true)}
            className="flex h-10 items-center gap-2 rounded-[12px] border border-[#e6e6e6] bg-amber-50 px-4 text-[13px] font-medium text-amber-700 transition hover:bg-amber-100/55"
          >
            <RefreshCw className="h-4 w-4" />
            <span>Reload Asterisk</span>
          </button>
          {activeTab === "list" ? (
            <button
              onClick={openCreateForm}
              className="flex h-10 items-center gap-2 rounded-[12px] bg-black px-4 text-[13px] font-medium text-white transition hover:bg-black/90"
            >
              <Plus className="h-4 w-4" />
              <span>Add SIP Trunk</span>
            </button>
          ) : (
            <button
              onClick={() => setActiveTab("list")}
              className="flex h-10 items-center rounded-[12px] border border-[#e6e6e6] bg-white px-4 text-[13px] font-medium text-black transition hover:bg-[#f7f7f5]"
            >
              Back to List
            </button>
          )}
        </div>
      </div>

      {activeTab === "list" ? (
        <div className="grid gap-6 lg:grid-cols-3">
          {/* Trunks List */}
          <div className="lg:col-span-2 space-y-4">
            {loading ? (
              <div className="flex h-[20vh] items-center justify-center">
                <p className="font-mono text-[11px] uppercase tracking-widest text-black/40">
                  Loading trunk list...
                </p>
              </div>
            ) : trunks.length === 0 ? (
              <div className="flex h-[200px] flex-col items-center justify-center rounded-[20px] border border-dashed border-[#e6e6e6] bg-white">
                <AudioLines className="h-8 w-8 text-black/10 mb-2" />
                <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-black/40">
                  No SIP trunks configured
                </p>
              </div>
            ) : (
              <div className="rounded-[20px] border border-[#e6e6e6] bg-white p-6 shadow-sm">
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse text-left text-[13px]">
                    <thead>
                      <tr className="border-b border-[#e6e6e6] text-black/40 font-mono text-[11px]">
                        <th className="py-2">Gateway Name</th>
                        <th className="py-2">Proxy / IP</th>
                        <th className="py-2">Auth Type</th>
                        <th className="py-2 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {trunks.map((t) => (
                        <tr key={t.id} className="border-b border-[#e6e6e6] hover:bg-[#fcfcfb]">
                          <td className="py-3">
                            <div className="font-medium text-black">{t.name}</div>
                            <div className="text-[11px] text-black/40">{t.workspaces?.name || "Workspace unavailable"}</div>
                          </td>
                          <td className="py-3 font-mono text-black/70">{t.sip_proxy}:{t.sip_port}</td>
                          <td className="py-3">
                            <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold font-mono ${
                              t.auth_type === "ip_auth"
                                ? "bg-blue-50 text-blue-700"
                                : "bg-purple-50 text-purple-700"
                            }`}>
                              {t.auth_type === "ip_auth" ? "IP AUTH" : "USERPASS"}
                            </span>
                          </td>
                          <td className="py-3 text-right space-x-2">
                            <button
                              onClick={() => fetchConfig(t.id)}
                              title="View Asterisk Config"
                              className={`inline-flex h-8 w-8 items-center justify-center rounded-[8px] border transition-all ${
                                selectedTrunkId === t.id
                                  ? "border-black bg-black text-white"
                                  : "border-[#e6e6e6] hover:bg-[#f7f7f5] text-black/60"
                              }`}
                            >
                              <AudioLines className="h-3.5 w-3.5" />
                            </button>
                            <button
                              onClick={() => openEditForm(t)}
                              className="inline-flex h-8 w-8 items-center justify-center rounded-[8px] border border-[#e6e6e6] hover:bg-[#f7f7f5]"
                            >
                              <Edit2 className="h-3.5 w-3.5 text-black/60" />
                            </button>
                            <button
                              onClick={() => confirmDelete(t.id)}
                              className="inline-flex h-8 w-8 items-center justify-center rounded-[8px] border border-red-100 hover:bg-red-50"
                            >
                              <Trash2 className="h-3.5 w-3.5 text-red-600" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Asterisk Configurations Panel */}
            {selectedTrunkId && (
              <div className="rounded-[20px] border border-[#e6e6e6] bg-white p-6 shadow-sm space-y-4">
                <div className="flex items-center justify-between border-b border-black/5 pb-3">
                  <h3 className="font-medium text-base text-black">
                    Asterisk Configuration: {trunks.find(t => t.id === selectedTrunkId)?.name}
                  </h3>
                  <button
                    onClick={() => { setSelectedTrunkId(null); setGeneratedConfig(null); }}
                    className="text-xs text-neutral-400 hover:text-black font-mono"
                  >
                    Close
                  </button>
                </div>

                {loadingConfig ? (
                  <div className="h-32 flex flex-col items-center justify-center space-y-2">
                    <RefreshCw className="h-5 w-5 animate-spin text-black/40" />
                    <p className="text-[10px] font-mono uppercase tracking-wider text-black/40">Generating configurations...</p>
                  </div>
                ) : generatedConfig ? (
                  <div className="space-y-4">
                    {/* PJSIP config */}
                    <div className="rounded-xl bg-black p-4 text-white font-mono text-xs overflow-x-auto relative">
                      <div className="flex justify-between items-center mb-2 text-neutral-400 border-b border-white/10 pb-1">
                        <span>pjsip.conf configuration block</span>
                        <button
                          onClick={() => handleCopy(generatedConfig.pjsip_conf, 'pjsip')}
                          className="h-6 w-6 inline-flex items-center justify-center text-white hover:bg-white/10 rounded"
                        >
                          {copiedField === 'pjsip' ? <Check className="h-3 w-3 text-green-400" /> : <Copy className="h-3 w-3" />}
                        </button>
                      </div>
                      <pre className="text-left whitespace-pre-wrap">{generatedConfig.pjsip_conf}</pre>
                    </div>

                    {/* Extensions config */}
                    <div className="rounded-xl bg-black p-4 text-white font-mono text-xs overflow-x-auto relative">
                      <div className="flex justify-between items-center mb-2 text-neutral-400 border-b border-white/10 pb-1">
                        <span>extensions.conf dialplan block</span>
                        <button
                          onClick={() => handleCopy(generatedConfig.extensions_conf, 'ext')}
                          className="h-6 w-6 inline-flex items-center justify-center text-white hover:bg-white/10 rounded"
                        >
                          {copiedField === 'ext' ? <Check className="h-3 w-3 text-green-400" /> : <Copy className="h-3 w-3" />}
                        </button>
                      </div>
                      <pre className="text-left whitespace-pre-wrap">{generatedConfig.extensions_conf}</pre>
                    </div>
                  </div>
                ) : (
                  <p className="text-xs text-neutral-400 font-mono">Could not generate Asterisk configuration for this trunk.</p>
                )}
              </div>
            )}
          </div>

          {/* Registration Console */}
          <div className="space-y-4">
            <div className="rounded-[20px] border border-[#e6e6e6] bg-black p-5 text-white shadow-sm flex flex-col h-[400px]">
              <div className="flex items-center justify-between mb-4">
                <span className="font-mono text-[10px] uppercase tracking-wider text-white/50">
                  Asterisk Registration Status
                </span>
                <button
                  onClick={fetchRegistrations}
                  disabled={loadingReg}
                  className="flex h-7 w-7 items-center justify-center rounded-[6px] border border-white/20 bg-white/5 hover:bg-white/10"
                >
                  <RefreshCw className={`h-3 w-3 text-white/80 ${loadingReg ? "animate-spin" : ""}`} />
                </button>
              </div>
              <pre className="flex-1 overflow-auto rounded-[10px] bg-white/5 p-3 font-mono text-[11px] leading-relaxed text-green-400 select-text whitespace-pre-wrap">
                {regOutput}
              </pre>
            </div>
          </div>
        </div>
      ) : (
        /* Create/Edit Form */
        <div className="max-w-2xl rounded-[20px] border border-[#e6e6e6] bg-white p-6 shadow-sm mx-auto">
          <h2 className="text-xl font-[480] text-black mb-6">
            {editId ? "Edit SIP Config" : "Add New SIP Gateway"}
          </h2>

          <form onSubmit={handleSave} className="space-y-5">
            <div className="space-y-1">
              <label className="text-[11px] font-mono uppercase tracking-wider text-black/50">Workspace Association</label>
              <select
                value={workspaceId}
                onChange={(e) => setWorkspaceId(e.target.value)}
                className="w-full rounded-[10px] border border-[#e6e6e6] bg-white px-3 py-2 text-[13px] text-black focus:outline-none focus:ring-1 focus:ring-black"
              >
                {workspaces.map((w) => (
                  <option key={w.id} value={w.id}>{w.name}</option>
                ))}
              </select>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1">
                <label className="text-[11px] font-mono uppercase tracking-wider text-black/50">Trunk Name</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Airtel Primary"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full rounded-[10px] border border-[#e6e6e6] px-3 py-2 text-[13px] text-black focus:outline-none"
                />
              </div>

              <div className="space-y-1">
                <label className="text-[11px] font-mono uppercase tracking-wider text-black/50">Provider Type</label>
                <select
                  value={providerType}
                  onChange={(e) => setProviderType(e.target.value)}
                  className="w-full rounded-[10px] border border-[#e6e6e6] bg-white px-3 py-2 text-[13px] text-black focus:outline-none"
                >
                  <option value="custom">Custom</option>
                  <option value="airtel">Airtel</option>
                  <option value="jio">Jio</option>
                  <option value="tata">Tata Communications</option>
                  <option value="twilio">Twilio</option>
                  <option value="exotel">Exotel</option>
                </select>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1">
                <label className="text-[11px] font-mono uppercase tracking-wider text-black/50">SIP Proxy Domain / IP</label>
                <input
                  type="text"
                  required
                  placeholder="sip.carrier.com"
                  value={sipProxy}
                  onChange={(e) => setSipProxy(e.target.value)}
                  className="w-full rounded-[10px] border border-[#e6e6e6] px-3 py-2 text-[13px] text-black focus:outline-none"
                />
              </div>

              <div className="space-y-1">
                <label className="text-[11px] font-mono uppercase tracking-wider text-black/50">SIP Port</label>
                <input
                  type="number"
                  required
                  value={sipPort}
                  onChange={(e) => setSipPort(parseInt(e.target.value) || 5060)}
                  className="w-full rounded-[10px] border border-[#e6e6e6] px-3 py-2 text-[13px] text-black focus:outline-none"
                />
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1">
                <label className="text-[11px] font-mono uppercase tracking-wider text-black/50">Authentication Method</label>
                <select
                  value={authType}
                  onChange={(e: any) => setAuthType(e.target.value)}
                  className="w-full rounded-[10px] border border-[#e6e6e6] bg-white px-3 py-2 text-[13px] text-black focus:outline-none"
                >
                  <option value="username_password">Username / Password Auth</option>
                  <option value="ip_auth">IP Authentication</option>
                </select>
              </div>

              <div className="space-y-1">
                <label className="text-[11px] font-mono uppercase tracking-wider text-black/50">Transport Protocol</label>
                <select
                  value={transport}
                  onChange={(e: any) => setTransport(e.target.value)}
                  className="w-full rounded-[10px] border border-[#e6e6e6] bg-white px-3 py-2 text-[13px] text-black focus:outline-none"
                >
                  <option value="udp">UDP</option>
                  <option value="tcp">TCP</option>
                  <option value="tls">TLS</option>
                </select>
              </div>
            </div>

            {authType === "username_password" ? (
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1">
                  <label className="text-[11px] font-mono uppercase tracking-wider text-black/50">SIP Username</label>
                  <input
                    type="text"
                    required
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    className="w-full rounded-[10px] border border-[#e6e6e6] px-3 py-2 text-[13px] text-black focus:outline-none"
                  />
                </div>

                <div className="space-y-1">
                  <label className="text-[11px] font-mono uppercase tracking-wider text-black/50">SIP Password</label>
                  <div className="relative">
                    <input
                      type={showPassword ? "text" : "password"}
                      placeholder={editId ? "Leave blank to keep unchanged" : ""}
                      required={!editId}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="w-full rounded-[10px] border border-[#e6e6e6] px-3 py-2 pr-10 text-[13px] text-black focus:outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="absolute right-3 top-2.5 text-black/40 hover:text-black"
                    >
                      {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <div className="space-y-1">
                <label className="text-[11px] font-mono uppercase tracking-wider text-black/50">Carrier Whitelisted IPs (Comma Separated)</label>
                <input
                  type="text"
                  placeholder="e.g. 192.168.1.1, 10.0.0.1"
                  value={providerIps}
                  onChange={(e) => setProviderIps(e.target.value)}
                  className="w-full rounded-[10px] border border-[#e6e6e6] px-3 py-2 text-[13px] text-black focus:outline-none"
                />
              </div>
            )}

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1">
                <label className="text-[11px] font-mono uppercase tracking-wider text-black/50">Outbound Caller ID (CID)</label>
                <input
                  type="text"
                  placeholder="e.g. +18166536732"
                  value={outboundCallerId}
                  onChange={(e) => setOutboundCallerId(e.target.value)}
                  className="w-full rounded-[10px] border border-[#e6e6e6] px-3 py-2 text-[13px] text-black focus:outline-none"
                />
              </div>

              <div className="space-y-1">
                <label className="text-[11px] font-mono uppercase tracking-wider text-black/50">Max Concurrent Capacity</label>
                <input
                  type="number"
                  value={maxCalls}
                  onChange={(e) => setMaxCalls(parseInt(e.target.value) || 10)}
                  className="w-full rounded-[10px] border border-[#e6e6e6] px-3 py-2 text-[13px] text-black focus:outline-none"
                />
              </div>
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
                Save Trunk Settings
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Delete Confirmation Alert */}
      <AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <AlertDialogContent className="rounded-[20px] border border-[#e6e6e6] bg-white p-6 shadow-xl">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-lg font-[480] text-black flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-red-500" />
              <span>Delete SIP Trunk Configuration</span>
            </AlertDialogTitle>
            <AlertDialogDescription className="text-[13px] text-black/60 font-[320] leading-relaxed">
              Are you completely sure you want to delete this SIP gateway? 
              This will remove all associated PJSIP configuration lines and trigger an Asterisk configuration regeneration.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className="mt-4 gap-2">
            <AlertDialogCancel className="rounded-[10px] border border-[#e6e6e6] text-[13px] font-medium hover:bg-[#f7f7f5]">
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              className="rounded-[10px] bg-red-600 text-[13px] font-medium text-white hover:bg-red-700"
            >
              Delete Trunk
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Asterisk Reload Confirmation Alert */}
      <AlertDialog open={reloadOpen} onOpenChange={setReloadOpen}>
        <AlertDialogContent className="rounded-[20px] border border-[#e6e6e6] bg-white p-6 shadow-xl">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-lg font-[480] text-black flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-amber-500" />
              <span>Trigger Asterisk Reload</span>
            </AlertDialogTitle>
            <AlertDialogDescription className="text-[13px] text-black/60 font-[320] leading-relaxed">
              Do you want to safely reload Asterisk PJSIP and Dialplan modules? 
              This will apply all newly created endpoints and update registration loops.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className="mt-4 gap-2">
            <AlertDialogCancel className="rounded-[10px] border border-[#e6e6e6] text-[13px] font-medium hover:bg-[#f7f7f5]">
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleReload}
              className="rounded-[10px] bg-amber-600 text-[13px] font-medium text-white hover:bg-amber-700"
            >
              Reload Configs
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
