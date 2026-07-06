import { createFileRoute } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { PhoneForwarded, Upload, PlayCircle, Clock, Loader2, Info } from 'lucide-react'
import { useWorkspace } from '@/context/WorkspaceContext'
import { toast } from 'sonner'

export const Route = createFileRoute('/_authenticated/dashboard/outbound')({
  component: OutboundPage,
})

interface AgentRecord {
  id: string;
  name: string;
}

function OutboundPage() {
  const { workspaceId, authHeaders, loading: contextLoading } = useWorkspace();
  const [loading, setLoading] = useState(true);
  const [agents, setAgents] = useState<AgentRecord[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [phoneNumber, setPhoneNumber] = useState("");
  const [calling, setCalling] = useState(false);

  const apiUrl = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

  useEffect(() => {
    if (contextLoading) return;
    if (!workspaceId || !authHeaders) {
      setLoading(false);
      return;
    }

    async function fetchWorkspaceAgents() {
      try {
        const res = await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/agents`, { headers: authHeaders || undefined });
        if (res.ok) {
          const data = await res.json();
          setAgents(data || []);
          if (data && data.length > 0) {
            setSelectedAgentId(data[0].id);
          }
        } else {
          toast.error("Failed to load workspace agents");
        }
      } catch (err) {
        console.error("Error loading agents:", err);
      } finally {
        setLoading(false);
      }
    }

    fetchWorkspaceAgents();
  }, [workspaceId, authHeaders, contextLoading, apiUrl]);

  async function handleQuickCall() {
    if (!workspaceId || !authHeaders) return;
    if (!selectedAgentId) {
      toast.error("Please choose a voice agent first");
      return;
    }
    const dialNumber = phoneNumber.trim();
    if (!dialNumber) {
      toast.error("Please enter a valid phone number");
      return;
    }

    setCalling(true);
    try {
      const res = await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/agents/${selectedAgentId}/test-call`, {
        method: "POST",
        headers: {
          ...authHeaders,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ to_number: dialNumber }),
      });
      const data = await res.json();
      if (res.ok) {
        toast.success("📞 Outbound call successfully initiated! Check the dialed phone.");
        setPhoneNumber("");
      } else {
        toast.error(data.detail || "Failed to trigger outbound call");
      }
    } catch (err) {
      toast.error("Network error triggering outbound call");
    } finally {
      setCalling(false);
    }
  }

  if (loading) {
    return (
      <div className="flex h-80 flex-col items-center justify-center space-y-4">
        <Loader2 className="h-10 w-10 animate-spin text-black opacity-20" />
        <p className="font-mono text-[12px] uppercase tracking-[0.2em] opacity-40">Loading outbound tools...</p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-8 px-4 py-3 md:px-5 md:py-4">
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-[#999999]">
          <PhoneForwarded className="h-3.5 w-3.5" />
          <span>Outbound Distribution</span>
        </div>
        <h1 className="text-4xl font-[340] tracking-[-0.03em] text-black md:text-5xl">Outbound Campaigns</h1>
        <p className="max-w-2xl text-[15px] font-[330] leading-relaxed text-black/60">
          Create and manage automated outbound calling campaigns.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {/* Quick Call Action */}
        <div className="flex flex-col rounded-[20px] border border-[#e6e6e6] bg-white p-6 shadow-sm">
          <div className="space-y-1 pb-4 mb-6 border-b border-[#f1f1f1]">
            <h3 className="text-[18px] font-[480] text-black flex items-center gap-2">
              <PhoneForwarded className="h-4 w-4 text-black opacity-60" />
              Quick Call
            </h3>
            <p className="text-[13px] text-black/60 font-[320] leading-relaxed">
              Make a single automated call immediately.
            </p>
          </div>
          <div className="space-y-4 flex-1">
            <div className="space-y-2.5">
              <Label className="font-mono text-[10px] uppercase tracking-widest text-[#999999]">Phone Number</Label>
              <Input 
                value={phoneNumber}
                onChange={(e) => setPhoneNumber(e.target.value)}
                placeholder="+91 98765-43210" 
                className="h-10 bg-[#f7f7f5] border-transparent rounded-[12px] px-4 text-[13px] font-[450] focus:bg-white transition-all" 
              />
            </div>
            <div className="space-y-2.5">
              <Label className="font-mono text-[10px] uppercase tracking-widest text-[#999999]">Select Agent</Label>
              {agents.length > 0 ? (
                <Select value={selectedAgentId} onValueChange={setSelectedAgentId}>
                  <SelectTrigger className="h-10 bg-[#f7f7f5] border-transparent rounded-[12px] px-4 text-[13px] font-[450]">
                    <SelectValue placeholder="Choose an agent" />
                  </SelectTrigger>
                  <SelectContent className="rounded-lg border-[#e6e6e6]">
                    {agents.map(a => (
                      <SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <p className="text-[12px] text-[#ff3d8b] italic">No active agents. Please create an agent first.</p>
              )}
            </div>
          </div>
          <div className="pt-4 border-t border-[#f1f1f1] mt-6">
            <Button 
              onClick={handleQuickCall}
              disabled={calling || agents.length === 0}
              className="w-full h-10 rounded-full bg-black text-white hover:bg-black/90 font-[480] text-[13px] gap-2 flex items-center justify-center border-none"
            >
              {calling ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Placing Call...
                </>
              ) : (
                <>
                  <PlayCircle className="h-4 w-4" />
                  Start Call Now
                </>
              )}
            </Button>
          </div>
        </div>

        {/* Batch Campaign */}
        <div className="flex flex-col lg:col-span-2 rounded-[20px] border border-[#e6e6e6] bg-white p-6 shadow-sm">
          <div className="space-y-1 pb-4 mb-6 border-b border-[#f1f1f1]">
            <h3 className="text-[18px] font-[480] text-black flex items-center gap-2">
              <Upload className="h-4 w-4 text-black opacity-60" />
              New Batch Campaign (Coming Soon)
            </h3>
            <p className="text-[13px] text-black/60 font-[320] leading-relaxed">
              Upload a list of leads to start an automated calling campaign.
            </p>
          </div>
          <div className="space-y-6 flex-1 opacity-50 pointer-events-none">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2.5">
                <Label className="font-mono text-[10px] uppercase tracking-widest text-[#999999]">Campaign Name</Label>
                <Input placeholder="e.g. Q3 Reactivation" className="h-10 bg-[#f7f7f5] border-transparent rounded-[12px] px-4 text-[13px] font-[450] focus:bg-white transition-all" />
              </div>
              <div className="space-y-2.5">
                <Label className="font-mono text-[10px] uppercase tracking-widest text-[#999999]">Select Agent</Label>
                <Select>
                  <SelectTrigger className="h-10 bg-[#f7f7f5] border-transparent rounded-[12px] px-4 text-[13px] font-[450]">
                    <SelectValue placeholder="Choose an agent" />
                  </SelectTrigger>
                  <SelectContent className="rounded-lg border-[#e6e6e6]">
                    <SelectItem value="agent1">Sales BDR</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            
            <div className="space-y-2.5">
              <Label className="font-mono text-[10px] uppercase tracking-widest text-[#999999]">Upload Contact List (CSV)</Label>
              <div className="border border-dashed border-[#e6e6e6] rounded-[16px] p-8 flex flex-col items-center justify-center text-center bg-[#f7f7f5]/30">
                <div className="h-9 w-9 rounded-full bg-[#f7f7f5] border border-[#e6e6e6] flex items-center justify-center mb-3">
                  <Upload className="h-4 w-4 text-black opacity-60" />
                </div>
                <h4 className="font-bold text-[13px] text-black">Click to upload or drag and drop</h4>
                <p className="text-[11px] text-black/50 mt-1 max-w-[250px] font-[320] leading-relaxed">
                  CSV must include a "phone" column. Optional columns: name, email, company.
                </p>
              </div>
            </div>
          </div>
          <div className="pt-4 border-t border-[#f1f1f1] mt-6 flex justify-between gap-4">
            <Button disabled variant="ghost" className="h-10 rounded-full px-5 text-[12px] font-[480] hover:bg-[#f7f7f5] border border-transparent hover:border-[#e6e6e6] gap-2 text-gray-400">
              <Clock className="h-4 w-4" />
              Schedule for Later
            </Button>
            <Button disabled className="h-10 rounded-full px-6 bg-gray-100 text-gray-400 hover:bg-gray-100 font-[480] text-[13px] gap-2 flex items-center justify-center border-none">
              <PlayCircle className="h-4 w-4" />
              Launch Campaign (Coming Soon)
            </Button>
          </div>
        </div>
      </div>
      
      {/* Active Campaigns List */}
      <div className="flex flex-col gap-3 mt-6">
        <h3 className="text-[20px] font-[480] text-black tracking-tight">Active & Recent Campaigns</h3>
        <div className="flex flex-col items-center justify-center border border-[#e6e6e6] bg-white rounded-[20px] p-10 text-center shadow-sm">
          <PhoneForwarded className="h-9 w-9 text-black/10 mb-3" />
          <h4 className="text-[15px] font-[480] text-black">No campaigns yet</h4>
          <p className="text-[13px] text-black/60 font-[320] leading-relaxed">
            Start a quick call or launch a batch campaign to see it here.
          </p>
        </div>
      </div>
    </div>
  )
}
