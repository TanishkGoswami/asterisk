import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { RefreshCw, Code, History, FileText, CheckCircle, AlertTriangle, Play, Undo } from "lucide-react";
import { toast } from "sonner";

export const Route = createFileRoute("/_authenticated/admin/asterisk-configs")({
  component: AsteriskConfigManager,
});

interface ConfigVersion {
  id: string;
  version_number: number;
  config_type: string;
  validation_status: string;
  validation_error: string | null;
  reload_status: string;
  reload_error: string | null;
  registration_status: string;
  registration_warning: string | null;
  rollback_available: boolean;
  is_active: boolean;
  rollback_of: string | null;
  created_at: string;
  applied_at: string | null;
}

interface FullConfigVersion extends ConfigVersion {
  pjsip_config: string;
  extensions_config: string;
}

function AsteriskConfigManager() {
  const [versions, setVersions] = useState<ConfigVersion[]>([]);
  const [selectedVersion, setSelectedVersion] = useState<FullConfigVersion | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [page, setPage] = useState(1);

  const fetchVersions = async () => {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const headers = { Authorization: `Bearer ${session.access_token}` };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

      const res = await fetch(`${apiUrl}/api/admin/asterisk/config-versions?limit=20&page=${page}`, { headers });
      if (!res.ok) throw new Error("Failed to load configuration history.");
      const data = await res.json();
      setVersions(data);
      
      // Auto-load details for first active version if none selected
      if (data.length > 0 && !selectedVersion) {
        fetchVersionDetail(data[0].id);
      }
    } catch (e: any) {
      toast.error(e.message || "Failed to load config history.");
    } finally {
      setLoading(false);
    }
  };

  const fetchVersionDetail = async (id: string) => {
    setDetailLoading(true);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const headers = { Authorization: `Bearer ${session.access_token}` };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

      const res = await fetch(`${apiUrl}/api/admin/asterisk/config-versions/${id}`, { headers });
      if (!res.ok) throw new Error("Failed to fetch configuration details.");
      const data = await res.json();
      setSelectedVersion(data);
    } catch (e: any) {
      toast.error(e.message || "Failed to load version contents.");
    } finally {
      setDetailLoading(false);
    }
  };

  const handleSafeReload = async () => {
    setReloading(true);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const headers = { Authorization: `Bearer ${session.access_token}` };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

      const res = await fetch(`${apiUrl}/api/admin/sip-trunks/reload-asterisk-safe`, {
        method: "POST",
        headers
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Safe config reload failed.");
      }

      toast.success("Safe config staged and reloaded successfully!");
      fetchVersions();
    } catch (e: any) {
      toast.error(e.message || "Error running reload.");
    } finally {
      setReloading(false);
    }
  };

  const handleRollback = async (id: string) => {
    if (!confirm("Are you sure you want to rollback Asterisk to this config state?")) return;
    
    setReloading(true);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;

      const headers = { Authorization: `Bearer ${session.access_token}` };
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";

      const res = await fetch(`${apiUrl}/api/admin/asterisk/config-versions/${id}/rollback`, {
        method: "POST",
        headers
      });

      if (!res.ok) throw new Error("Rollback action failed.");
      
      toast.success("Rollback executed and Asterisk configs successfully updated!");
      fetchVersions();
    } catch (e: any) {
      toast.error(e.message || "Error deploying rollback.");
    } finally {
      setReloading(false);
    }
  };

  useEffect(() => {
    fetchVersions();
  }, [page]);

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-black/50">
            <History className="h-3.5 w-3.5" />
            <span>Config Staging</span>
          </div>
          <h1 className="text-4xl font-[340] tracking-[-0.03em] text-black">Asterisk Staged History</h1>
          <p className="max-w-2xl text-[14px] font-[320] leading-relaxed text-black/60">
            Audit staged trunk updates, review validation checks, and rollback Asterisk endpoints safely.
          </p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={handleSafeReload}
            disabled={reloading}
            className="h-10 px-4 bg-black text-white rounded-[10px] text-[13px] font-medium transition hover:bg-black/90 disabled:opacity-60 flex items-center gap-2"
          >
            <Play className="h-3.5 w-3.5" />
            <span>Trigger Safe Reload</span>
          </button>
          <button
            onClick={fetchVersions}
            className="flex h-10 w-10 items-center justify-center rounded-[12px] border border-[#e6e6e6] bg-white transition hover:bg-[#f7f7f5]"
          >
            <RefreshCw className="h-4 w-4 text-black/60" />
          </button>
        </div>
      </div>

      {loading ? (
        <div className="flex h-[40vh] items-center justify-center">
          <p className="font-mono text-[12px] uppercase tracking-widest text-black/40">
            Loading configuration timeline...
          </p>
        </div>
      ) : (
        <div className="grid gap-8 lg:grid-cols-3">
          {/* History List */}
          <div className="rounded-[20px] border border-[#e6e6e6] bg-white p-5 shadow-sm space-y-4 max-h-[70vh] overflow-y-auto">
            <h2 className="text-[15px] font-[340] text-black border-b border-[#e6e6e6] pb-3 flex items-center gap-2">
              <History className="h-4 w-4 text-black/50" />
              <span>Deployment Timeline</span>
            </h2>

            <div className="space-y-3">
              {versions.map((ver) => (
                <div
                  key={ver.id}
                  onClick={() => fetchVersionDetail(ver.id)}
                  className={`p-4 rounded-[14px] border transition cursor-pointer text-left ${
                    selectedVersion?.id === ver.id
                      ? "border-black bg-[#fcfcfb]"
                      : "border-[#e6e6e6] bg-white hover:bg-[#fafaf9]"
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-mono text-[13px] font-semibold text-black">
                      v{ver.version_number}
                    </span>
                    {ver.is_active && (
                      <span className="rounded-full bg-green-50 px-2 py-0.5 text-[9px] font-bold uppercase text-green-700">
                        Active Config
                      </span>
                    )}
                  </div>

                  <div className="space-y-1.5 text-[12px] text-black/60">
                    <div className="flex justify-between">
                      <span>Validation:</span>
                      <span className={ver.validation_status === "passed" ? "text-green-600 font-medium" : "text-red-500 font-medium"}>
                        {ver.validation_status.toUpperCase()}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span>Reload Code:</span>
                      <span className={ver.reload_status === "success" ? "text-green-600 font-medium" : "text-red-500 font-medium"}>
                        {ver.reload_status.toUpperCase()}
                      </span>
                    </div>
                    {ver.rollback_of && (
                      <div className="text-[10px] text-amber-600 font-mono">
                        Reverted from rollback
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Config Inspector / Diffs */}
          <div className="lg:col-span-2 space-y-6">
            {detailLoading || !selectedVersion ? (
              <div className="rounded-[20px] border border-[#e6e6e6] bg-white p-12 text-center shadow-sm">
                <p className="font-mono text-[12px] text-black/40 uppercase tracking-widest">
                  Loading version config inspection...
                </p>
              </div>
            ) : (
              <div className="rounded-[20px] border border-[#e6e6e6] bg-white p-6 shadow-sm space-y-6">
                <div className="flex justify-between items-center border-b border-[#e6e6e6] pb-4">
                  <div>
                    <h2 className="text-[18px] font-[340] text-black">
                      Configuration Version {selectedVersion.version_number}
                    </h2>
                    <p className="text-[12px] text-black/50 font-mono mt-0.5">
                      Deployed on: {new Date(selectedVersion.created_at).toLocaleString()}
                    </p>
                  </div>
                  {!selectedVersion.is_active && selectedVersion.reload_status === "success" && (
                    <button
                      onClick={() => handleRollback(selectedVersion.id)}
                      className="h-9 px-3.5 bg-[#f2f2f0] border border-[#d6d6d4] text-black rounded-[8px] text-[12px] font-semibold transition hover:bg-[#fafaf8] flex items-center gap-1.5"
                    >
                      <Undo className="h-3.5 w-3.5" />
                      <span>Rollback to this state</span>
                    </button>
                  )}
                </div>

                {/* Validation warnings */}
                {selectedVersion.reload_error && (
                  <div className="flex items-start gap-2.5 rounded-[12px] border border-red-100 bg-red-50/50 p-3 text-[13px] text-red-700">
                    <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                    <span>{selectedVersion.reload_error}</span>
                  </div>
                )}

                {/* Masked config viewer */}
                <div className="grid gap-6 md:grid-cols-2">
                  <div className="space-y-2">
                    <label className="text-[11px] font-mono uppercase text-black/40 block flex items-center gap-1">
                      <Code className="h-3 w-3" />
                      <span>pjsip_trunks.conf (Masked)</span>
                    </label>
                    <pre className="p-4 rounded-[12px] border border-[#e6e6e6] bg-[#fcfcfb] text-[11px] font-mono text-black/75 overflow-auto max-h-[350px] text-left whitespace-pre-wrap">
                      {selectedVersion.pjsip_config || "; No PJSIP configuration staged."}
                    </pre>
                  </div>

                  <div className="space-y-2">
                    <label className="text-[11px] font-mono uppercase text-black/40 block flex items-center gap-1">
                      <FileText className="h-3 w-3" />
                      <span>extensions_trunks.conf (Redacted)</span>
                    </label>
                    <pre className="p-4 rounded-[12px] border border-[#e6e6e6] bg-[#fcfcfb] text-[11px] font-mono text-black/75 overflow-auto max-h-[350px] text-left whitespace-pre-wrap">
                      {selectedVersion.extensions_config || "; No Dialplan configuration staged."}
                    </pre>
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
