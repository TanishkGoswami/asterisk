import { createFileRoute } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Blocks, Key, Webhook, Loader2, Info } from 'lucide-react'
import { useWorkspace } from '@/context/WorkspaceContext'
import { toast } from 'sonner'

export const Route = createFileRoute('/_authenticated/dashboard/integrations')({
  component: IntegrationsPage,
})

function IntegrationsPage() {
  const { workspaceId, authHeaders, loading: contextLoading } = useWorkspace();
  const [loading, setLoading] = useState(true);
  const [savingWebhook, setSavingWebhook] = useState(false);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [isEditingWebhook, setIsEditingWebhook] = useState(false);

  const apiUrl = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

  useEffect(() => {
    if (contextLoading) return;
    if (!workspaceId || !authHeaders) {
      setLoading(false);
      return;
    }

    async function fetchWebhookSetting() {
      try {
        const res = await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/settings`, { headers: authHeaders || undefined });
        if (res.ok) {
          const data = await res.json();
          setWebhookUrl(data.webhook_url || "");
        }
      } catch (err) {
        console.error("Error loading webhook integrations:", err);
      } finally {
        setLoading(false);
      }
    }

    fetchWebhookSetting();
  }, [workspaceId, authHeaders, contextLoading, apiUrl]);

  async function handleSaveWebhook() {
    if (!workspaceId || !authHeaders) return;
    setSavingWebhook(true);
    try {
      const res = await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/settings`, {
        method: "PATCH",
        headers: {
          ...authHeaders,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ webhook_url: webhookUrl }),
      });
      if (res.ok) {
        toast.success("Webhook URL updated successfully");
        setIsEditingWebhook(false);
      } else {
        const err = await res.json().catch(() => ({}));
        toast.error(err.detail || "Failed to update webhook URL");
      }
    } catch (err) {
      toast.error("Network error saving webhook settings");
    } finally {
      setSavingWebhook(false);
    }
  }

  if (loading) {
    return (
      <div className="flex h-80 flex-col items-center justify-center space-y-4">
        <Loader2 className="h-10 w-10 animate-spin text-black opacity-20" />
        <p className="font-mono text-[12px] uppercase tracking-[0.2em] opacity-40">Loading integrations...</p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-8 px-4 py-3 md:px-5 md:py-4">
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-[#999999]">
          <Blocks className="h-3.5 w-3.5" />
          <span>Integration Hub</span>
        </div>
        <h1 className="text-4xl font-[340] tracking-[-0.03em] text-black md:text-5xl">Integrations</h1>
        <p className="max-w-2xl text-[15px] font-[330] leading-relaxed text-black/60">
          Connect external systems, manage API keys, and configure webhooks.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* API Keys Card */}
        <div className="flex flex-col rounded-[20px] border border-[#e6e6e6] bg-white p-6 shadow-sm">
          <div className="space-y-1 pb-4 mb-6 border-b border-[#f1f1f1]">
            <h3 className="text-[18px] font-[480] text-black flex items-center gap-2">
              <Key className="h-4 w-4 text-black opacity-60" />
              API Keys
            </h3>
            <p className="text-[13px] text-black/60 font-[320] leading-relaxed">
              Use these keys to authenticate API requests from your application.
            </p>
          </div>
          <div className="space-y-4 flex-1">
            <div className="space-y-2.5">
              <div className="font-mono text-[10px] uppercase tracking-widest text-[#999999]">Secret Key</div>
              <div className="flex gap-2">
                <Input type="password" value="No API key generated" readOnly className="h-10 bg-[#f7f7f5] border-transparent rounded-[12px] px-4 text-[13px] font-[450] text-[#999999]" />
                <Button disabled variant="outline" className="h-10 rounded-[12px] border-[#e6e6e6] text-[#999999] hover:bg-[#f7f7f5] text-[12px] font-[480] px-5">Copy</Button>
              </div>
            </div>
          </div>
          <div className="pt-4 border-t border-[#f1f1f1] mt-6">
            <Button disabled variant="ghost" className="h-9 rounded-full px-5 text-[12px] font-[480] hover:bg-[#f7f7f5] border border-transparent hover:border-[#e6e6e6] text-gray-400">Generate New Key (Coming Soon)</Button>
          </div>
        </div>

        {/* Webhooks Card */}
        <div className="flex flex-col rounded-[20px] border border-[#e6e6e6] bg-white p-6 shadow-sm">
          <div className="space-y-1 pb-4 mb-6 border-b border-[#f1f1f1]">
            <h3 className="text-[18px] font-[480] text-black flex items-center gap-2">
              <Webhook className="h-4 w-4 text-black opacity-60" />
              Webhooks
            </h3>
            <p className="text-[13px] text-black/60 font-[320] leading-relaxed">
              Receive real-time updates about call status and transcripts.
            </p>
          </div>
          <div className="space-y-4 flex-1">
            {isEditingWebhook ? (
              <div className="space-y-3">
                <Input
                  value={webhookUrl}
                  onChange={(e) => setWebhookUrl(e.target.value)}
                  placeholder="https://your-domain.com/webhooks/voicepilot"
                  className="h-10 bg-[#f7f7f5] border-transparent rounded-[12px] px-4 text-[13px] font-[450]"
                />
                <div className="flex gap-2">
                  <Button size="sm" onClick={handleSaveWebhook} disabled={savingWebhook} className="bg-[#c5b0f4] text-black hover:bg-[#c5b0f4]/90 h-8 rounded-lg text-[11px] font-[480]">
                    {savingWebhook ? "Saving..." : "Save"}
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setIsEditingWebhook(false)} className="h-8 rounded-lg text-[11px] border-[#e6e6e6] hover:bg-[#f7f7f5]">
                    Cancel
                  </Button>
                </div>
              </div>
            ) : (
              <div className="rounded-[14px] border border-[#e6e6e6] p-4 bg-[#f7f7f5]/30">
                <h4 className="text-[13px] font-bold mb-1">
                  {webhookUrl ? "Active Webhook Endpoint" : "No Webhook Configured"}
                </h4>
                <p className="text-[11px] text-black/50 mb-3 truncate">
                  {webhookUrl || "Add an endpoint to receive real-time updates."}
                </p>
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" onClick={() => setIsEditingWebhook(true)} className="h-8 rounded-lg text-[11px] border-[#e6e6e6] hover:bg-[#f7f7f5]">
                    {webhookUrl ? "Edit" : "Configure Webhook"}
                  </Button>
                </div>
              </div>
            )}
          </div>
          <div className="pt-4 border-t border-[#f1f1f1] mt-6 flex items-center gap-1.5 text-[#999999]">
            <Info className="h-3.5 w-3.5" />
            <span className="text-[11px] font-[320]">Workspace scoped webhooks.</span>
          </div>
        </div>

        {/* Third-Party Integrations */}
        <div className="md:col-span-2 flex flex-col rounded-[20px] border border-[#e6e6e6] bg-white p-6 shadow-sm">
          <div className="space-y-1 pb-4 mb-6 border-b border-[#f1f1f1]">
            <h3 className="text-[18px] font-[480] text-black flex items-center gap-2">
              <Blocks className="h-4 w-4 text-black opacity-60" />
              Third-Party Integrations
            </h3>
            <p className="text-[13px] text-black/60 font-[320] leading-relaxed">
              Native integrations with CRMs and external platforms.
            </p>
          </div>
          <div className="grid sm:grid-cols-2 md:grid-cols-3 gap-4">
            {['HubSpot', 'Salesforce', 'Make.com', 'Zapier', 'Slack', 'Zendesk'].map(integration => (
              <div key={integration} className="flex items-center justify-between p-4 rounded-[14px] border border-[#e6e6e6] bg-gray-50/50">
                <span className="font-medium text-[13px] text-gray-400">{integration}</span>
                <Button disabled variant="outline" size="sm" className="h-8 rounded-lg text-[11px] border-[#e6e6e6] text-gray-300 bg-white">Coming Soon</Button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
