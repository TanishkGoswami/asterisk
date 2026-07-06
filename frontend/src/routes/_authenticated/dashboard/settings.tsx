import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Settings as SettingsIcon, Sliders, Loader2 } from "lucide-react";
import { useWorkspace } from "@/context/WorkspaceContext";
import { toast } from "sonner";

export const Route = createFileRoute("/_authenticated/dashboard/settings")({
  component: SettingsPage,
  validateSearch: (search: Record<string, unknown>) => {
    return {
      tab: (search.tab as string) || "general",
    };
  },
});

function SettingsPage() {
  const { tab } = Route.useSearch();
  const { workspaceId, authHeaders, loading: contextLoading } = useWorkspace();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [settings, setSettings] = useState({
    name: "",
    timezone: "",
    billing_email: "",
    webhook_url: "",
  });

  const apiUrl = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

  useEffect(() => {
    if (contextLoading) return;
    if (!workspaceId || !authHeaders) {
      setLoading(false);
      return;
    }

    async function fetchSettings() {
      try {
        const res = await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/settings`, { headers: authHeaders || undefined });
        if (res.ok) {
          const data = await res.json();
          setSettings({
            name: data.name || "",
            timezone: data.timezone || "UTC",
            billing_email: data.billing_email || "",
            webhook_url: data.webhook_url || "",
          });
        } else {
          toast.error("Failed to load workspace settings");
        }
      } catch (err) {
        console.error("Error loading settings:", err);
      } finally {
        setLoading(false);
      }
    }

    fetchSettings();
  }, [workspaceId, authHeaders, contextLoading, apiUrl]);

  async function handleSave() {
    if (!workspaceId || !authHeaders) return;
    setSaving(true);
    try {
      const res = await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/settings`, {
        method: "PATCH",
        headers: {
          ...authHeaders,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(settings),
      });
      if (res.ok) {
        toast.success("Settings saved successfully");
      } else {
        const err = await res.json().catch(() => ({}));
        toast.error(err.detail || "Failed to save settings");
      }
    } catch (err) {
      toast.error("Network error saving settings");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex h-80 flex-col items-center justify-center space-y-4">
        <Loader2 className="h-10 w-10 animate-spin text-black opacity-20" />
        <p className="font-mono text-[12px] uppercase tracking-[0.2em] opacity-40">Loading settings...</p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-8 px-4 py-3 md:px-5 md:py-4">
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-[#999999]">
          <Sliders className="h-3.5 w-3.5" />
          <span>System Configuration</span>
        </div>
        <h1 className="text-4xl font-[340] tracking-[-0.03em] text-black md:text-5xl">Settings</h1>
        <p className="text-[#666666] text-[18px] max-w-2xl font-[320] leading-relaxed">
          Manage your workspace identity, configuration parameters, and contact emails.
        </p>
      </div>

      <Tabs defaultValue={tab} className="w-full">
        <TabsContent value="general" className="space-y-8 animate-in fade-in duration-500">
          <div className="bg-white border border-[#e6e6e6] rounded-[24px] overflow-hidden">
            <div className="p-8 border-b border-[#f1f1f1]">
              <div className="flex items-center gap-3 mb-1">
                <SettingsIcon className="h-5 w-5 text-black opacity-60" />
                <h3 className="text-[20px] font-[480] text-black">Workspace Profile</h3>
              </div>
              <p className="text-[14px] text-[#666666] font-[320]">Update your organizational identity and properties.</p>
            </div>
            <div className="p-8 space-y-8 max-w-2xl">
              <div className="space-y-2.5">
                <Label className="font-mono text-[11px] uppercase tracking-[0.1em] text-[#999999]">Workspace Name</Label>
                <Input 
                  value={settings.name} 
                  onChange={(e) => setSettings({ ...settings, name: e.target.value })}
                  className="h-11 bg-[#f7f7f5] border-transparent rounded-[12px] px-4 text-[14px] font-[450] focus:bg-white transition-all" 
                />
              </div>
              <div className="space-y-2.5">
                <Label className="font-mono text-[11px] uppercase tracking-[0.1em] text-[#999999]">Workspace ID</Label>
                <div className="flex gap-2">
                  <Input
                    value={workspaceId || ""}
                    readOnly
                    className="h-11 bg-[#f7f7f5] border-transparent rounded-[12px] px-4 font-mono text-[11px] text-[#666666]"
                  />
                  <Button 
                    variant="outline" 
                    onClick={() => {
                      if (workspaceId) {
                        navigator.clipboard.writeText(workspaceId);
                        toast.success("Workspace ID copied to clipboard");
                      }
                    }}
                    className="h-11 rounded-[12px] border-[#e6e6e6] hover:bg-[#f7f7f5] text-[12px] font-[480] px-6"
                  >
                    Copy
                  </Button>
                </div>
              </div>
              <div className="h-px w-full bg-[#f1f1f1]" />
              <div className="space-y-2.5">
                <Label className="font-mono text-[11px] uppercase tracking-[0.1em] text-[#999999]">Operational Timezone</Label>
                <p className="text-[12px] text-[#999999] font-[320] italic">
                  Used for scheduling automated campaigns and reporting windows.
                </p>
                <Input 
                  value={settings.timezone} 
                  onChange={(e) => setSettings({ ...settings, timezone: e.target.value })}
                  className="h-11 bg-[#f7f7f5] border-transparent rounded-[12px] px-4 text-[14px] font-[450]" 
                />
              </div>
              <div className="h-px w-full bg-[#f1f1f1]" />
              <div className="space-y-2.5">
                <Label className="font-mono text-[11px] uppercase tracking-[0.1em] text-[#999999]">Billing Notification Email</Label>
                <Input 
                  value={settings.billing_email} 
                  onChange={(e) => setSettings({ ...settings, billing_email: e.target.value })}
                  placeholder="billing@yourdomain.com"
                  className="h-11 bg-[#f7f7f5] border-transparent rounded-[12px] px-4 text-[14px] font-[450]" 
                />
              </div>
              <div className="h-px w-full bg-[#f1f1f1]" />
              <div className="space-y-2.5">
                <Label className="font-mono text-[11px] uppercase tracking-[0.1em] text-[#999999]">Workspace Webhook URL</Label>
                <Input 
                  value={settings.webhook_url} 
                  onChange={(e) => setSettings({ ...settings, webhook_url: e.target.value })}
                  placeholder="https://your-api.com/webhooks/voicepilot"
                  className="h-11 bg-[#f7f7f5] border-transparent rounded-[12px] px-4 text-[14px] font-[450]" 
                />
              </div>
            </div>
            <div className="p-8 bg-[#f7f7f5]/30 border-t border-[#f1f1f1]">
              <Button 
                onClick={handleSave}
                disabled={saving}
                className="h-12 rounded-full px-10 bg-[#c5b0f4] text-black hover:bg-[#c5b0f4]/90 font-[480] text-[14px]"
              >
                {saving ? "Saving..." : "Save Changes"}
              </Button>
            </div>
          </div>

          <div className="bg-[#1f1d3d] border border-black rounded-[24px] overflow-hidden shadow-xl text-white">
            <div className="p-8 border-b border-white/10 bg-white/5">
              <h3 className="text-[18px] font-[480]">System Termination Area</h3>
              <p className="text-[13px] text-white/60 font-[320]">Irreversible actions for this intelligence environment.</p>
            </div>
            <div className="p-8">
              <div className="flex items-center justify-between p-6 rounded-[16px] border border-white/10 bg-white/5">
                <div>
                  <p className="font-[480] text-[15px]">Delete Workspace</p>
                  <p className="text-[13px] text-white/60 font-[320]">Permanently remove all agents, intelligence history, and distribution data.</p>
                </div>
                <Button 
                  disabled
                  className="h-10 rounded-full px-8 bg-[#ff3d8b]/50 text-white cursor-not-allowed transition-all font-[480] text-[13px] border-none"
                >
                  Terminate (Disabled)
                </Button>
              </div>
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
