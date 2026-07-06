import { createFileRoute } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { 
  Table, 
  TableBody, 
  TableCell, 
  TableHead, 
  TableHeader, 
  TableRow 
} from '@/components/ui/table'
import { 
  Dialog, 
  DialogContent, 
  DialogDescription, 
  DialogFooter, 
  DialogHeader, 
  DialogTitle, 
  DialogTrigger 
} from '@/components/ui/dialog'
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from '@/components/ui/select'
import { PhoneForwarded, AlertTriangle, Info, Plus, Upload, Loader2, Play } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useWorkspace } from '@/context/WorkspaceContext'
import { toast } from 'sonner'

export const Route = createFileRoute('/_authenticated/dashboard/batch-call')({
  component: BatchCallPage,
})

function BatchCallPage() {
  const { workspaceId, authHeaders, loading: contextLoading } = useWorkspace();
  const [agents, setAgents] = useState<any[]>([]);
  const [loadingAgents, setLoadingAgents] = useState(false);
  const [campaigns] = useState<any[]>([]);
  const [isOpen, setIsOpen] = useState(false);

  // Dialog fields
  const [campaignName, setCampaignName] = useState("");
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [concurrency, setConcurrency] = useState("5");
  const [startTime, setStartTime] = useState("now");

  const apiUrl = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

  useEffect(() => {
    if (contextLoading) return;
    if (!workspaceId || !authHeaders) return;

    async function fetchWorkspaceAgents() {
      setLoadingAgents(true);
      try {
        const res = await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/agents`, { headers: authHeaders || undefined });
        if (res.ok) {
          const data = await res.json();
          setAgents(data || []);
          if (data && data.length > 0) {
            setSelectedAgentId(data[0].id);
          }
        }
      } catch (err) {
        console.error("Error loading agents:", err);
      } finally {
        setLoadingAgents(false);
      }
    }

    fetchWorkspaceAgents();
  }, [workspaceId, authHeaders, contextLoading, apiUrl]);

  function handleLaunchCampaign() {
    if (!campaignName.trim()) {
      toast.error("Please enter a campaign name");
      return;
    }
    if (!selectedAgentId) {
      toast.error("Please select a voice agent");
      return;
    }
    
    // Notify the user about beta status
    toast.info("Launch restricted: Batch campaign scheduling is undergoing backend validation. Single outbound calls can be placed via the Outbound quick dialer.");
    setIsOpen(false);
    setCampaignName("");
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-8 px-4 py-3 md:px-5 md:py-4">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div className="space-y-3">
          <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-[#999999]">
            <PhoneForwarded className="h-3.5 w-3.5" />
            <span>Mass Distribution</span>
          </div>
          <h1 className="text-4xl font-[340] tracking-[-0.03em] text-black md:text-5xl">Batch Call</h1>
          <p className="max-w-2xl text-[15px] font-[330] leading-relaxed text-black/60">
            Automate outbound call campaigns at scale with high-concurrency voice engines.
          </p>
        </div>
        
        <Dialog open={isOpen} onOpenChange={setIsOpen}>
          <DialogTrigger asChild>
            <Button className="h-9 shrink-0 rounded-full bg-[#c5b0f4] text-black hover:bg-[#c5b0f4]/90 px-5 text-[13px] font-[480] transition-all duration-200 gap-2">
              <Plus className="h-4 w-4" />
              New Campaign
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-[480px] rounded-[24px] border border-[#e6e6e6] bg-white p-6 shadow-xl">
            <DialogHeader className="space-y-1.5 text-left">
              <DialogTitle className="text-[22px] font-[480] text-black">Create Campaign</DialogTitle>
              <DialogDescription className="text-[13px] text-black/60 font-[320]">
                Configure your campaign parameters and upload your contact list.
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-5 py-4 text-left">
              <div className="space-y-2">
                <Label className="text-[10px] font-mono uppercase tracking-widest text-[#999999]">Campaign Name</Label>
                <Input
                  value={campaignName}
                  onChange={(e) => setCampaignName(e.target.value)}
                  placeholder="e.g. Summer Sales"
                  className="h-11 bg-[#f7f7f5] border-transparent rounded-[12px] px-4 text-[13px] font-[450] focus:bg-white transition-all"
                />
              </div>

              <div className="space-y-2">
                <Label className="text-[10px] font-mono uppercase tracking-widest text-[#999999]">AI Agent</Label>
                {loadingAgents ? (
                  <div className="h-11 flex items-center justify-center bg-[#f7f7f5] rounded-[12px] border border-transparent">
                    <Loader2 className="h-4 w-4 animate-spin text-[#999999] mr-2" />
                    <span className="text-[12px] text-[#999999] font-mono">Loading agents...</span>
                  </div>
                ) : agents.length > 0 ? (
                  <Select value={selectedAgentId} onValueChange={setSelectedAgentId}>
                    <SelectTrigger className="h-11 bg-[#f7f7f5] border-transparent rounded-[12px] px-4 text-[13px] font-[450]">
                      <SelectValue placeholder="Choose agent" />
                    </SelectTrigger>
                    <SelectContent className="rounded-lg border-[#e6e6e6]">
                      {agents.map((ag) => (
                        <SelectItem key={ag.id} value={ag.id}>{ag.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <div className="h-11 flex items-center px-4 bg-[#f7f7f5] rounded-[12px] text-[12px] text-[#ff3d8b] italic">
                    No active agents. Please create an agent first.
                  </div>
                )}
              </div>

              <div className="space-y-2">
                <Label className="text-[10px] font-mono uppercase tracking-widest text-[#999999]">Contacts (CSV)</Label>
                <div className="flex flex-col items-center justify-center border border-dashed border-[#e6e6e6] rounded-[16px] p-8 bg-[#f7f7f5]/50 hover:bg-white hover:border-black/20 transition-all cursor-pointer">
                  <Upload className="h-6 w-6 text-[#999999] mb-3" />
                  <p className="text-[13px] text-black font-[450]">Drop your CSV file here</p>
                  <p className="text-[11px] text-[#999999] font-[320] mt-1 italic">Expected columns: Name, Phone</p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label className="text-[10px] font-mono uppercase tracking-widest text-[#999999]">Concurrency</Label>
                  <Select value={concurrency} onValueChange={setConcurrency}>
                    <SelectTrigger className="h-11 bg-[#f7f7f5] border-transparent rounded-[12px] text-[13px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="rounded-lg border-[#e6e6e6]">
                      <SelectItem value="5">5 (Standard)</SelectItem>
                      <SelectItem value="20">20 (High Volume)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label className="text-[10px] font-mono uppercase tracking-widest text-[#999999]">Start Time</Label>
                  <Select value={startTime} onValueChange={setStartTime}>
                    <SelectTrigger className="h-11 bg-[#f7f7f5] border-transparent rounded-[12px] text-[13px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="rounded-lg border-[#e6e6e6]">
                      <SelectItem value="now">Immediate</SelectItem>
                      <SelectItem value="scheduled">Scheduled</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </div>

            <DialogFooter>
              <Button onClick={handleLaunchCampaign} disabled={agents.length === 0} className="w-full h-12 rounded-full bg-[#c5b0f4] text-black hover:bg-[#c5b0f4]/90 text-[14px] font-[480] border-none">
                Launch Campaign
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {/* Warning banner indicating Super-Admin isolation */}
      <div className="flex items-start gap-3 rounded-[16px] border border-[#ff3d8b]/20 bg-[#ff3d8b]/5 p-4 text-[#ff3d8b]">
        <AlertTriangle className="h-5 w-5 shrink-0 mt-0.5" />
        <div className="space-y-1">
          <p className="text-[14px] font-[500]">Batch Campaigns are Protected Admin Operations</p>
          <p className="text-[13px] opacity-80 font-[320] leading-relaxed">
            Outbound batch dialer campaigns consume high concurrency trunk capacity and require Super-Admin privileges. Regular workspace members can initiate singular outbound test calls using the Outbound Quick Call interface.
          </p>
        </div>
      </div>

      <div className="grid gap-3 grid-cols-1 md:grid-cols-3">
        <div className="space-y-1.5 rounded-[16px] border border-[#e6e6e6] bg-[#f7f7f5] p-4 shadow-sm">
          <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-[#999999]">Active Channels</p>
          <div className="text-[24px] font-[450] text-black">0 / 0</div>
          <p className="font-mono text-[9px] uppercase tracking-tight italic text-[#ff3d8b]">Restricted feature</p>
        </div>
        <div className="space-y-1.5 rounded-[16px] border border-[#e6e6e6] bg-[#f7f7f5] p-4 text-black shadow-sm">
          <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-[#999999]">Total Reach</p>
          <div className="text-[24px] font-[450]">0</div>
          <div className="flex items-center gap-1.5 font-mono text-[9px] text-[#999999]">
            <Info className="h-3 w-3" />
            <span>Across 0 campaigns</span>
          </div>
        </div>
        <div className="space-y-1.5 rounded-[16px] border border-[#e6e6e6] bg-[#f7f7f5] p-4 shadow-sm">
          <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-[#999999]">Connection Rate</p>
          <div className="text-[24px] font-[450] text-black">0%</div>
          <p className="font-mono text-[9px] uppercase tracking-tight italic text-[#999999]">No data yet</p>
        </div>
      </div>

      <div className="overflow-hidden rounded-[16px] border border-[#e6e6e6] bg-white shadow-sm">
        <div className="border-b border-black/5 bg-[#f7f7f5] p-4 text-black">
          <h3 className="text-[16px] font-[480] tracking-tight">Active Distribution Campaigns</h3>
          <p className="text-[12px] font-[320] text-black/60">Monitor and control your automated outbound efforts in real-time.</p>
        </div>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader className="bg-[#f7f7f5]/50">
              <TableRow className="border-b border-[#f1f1f1] hover:bg-transparent">
                <TableHead className="px-4 py-2 font-mono text-[9px] uppercase tracking-[0.16em]">Campaign Name</TableHead>
                <TableHead className="py-2 font-mono text-[9px] uppercase tracking-[0.16em]">Agent</TableHead>
                <TableHead className="py-2 font-mono text-[9px] uppercase tracking-[0.16em]">Status</TableHead>
                <TableHead className="w-[180px] py-2 font-mono text-[9px] uppercase tracking-[0.16em]">Progress</TableHead>
                <TableHead className="py-2 font-mono text-[9px] uppercase tracking-[0.16em]">Conversion</TableHead>
                <TableHead className="px-4 py-2 text-right font-mono text-[9px] uppercase tracking-[0.16em]">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {campaigns.length > 0 ? (
                campaigns.map((camp) => (
                    <TableRow key={camp.id} className="border-b border-[#f1f1f1] hover:bg-[#f7f7f5]/20">
                      <TableCell className="px-4 py-2">
                        <div className="flex flex-col">
                          <span className="font-[480] text-black">{camp.name}</span>
                          <span className="text-[10px] text-[#999999] font-mono uppercase">{camp.id}</span>
                        </div>
                      </TableCell>
                      <TableCell className="text-[#666666] text-[13px]">{camp.agent}</TableCell>
                    <TableCell>
                      <span className={`px-2 py-0.5 rounded-sm text-[10px] font-mono uppercase tracking-wider ${
                        camp.status === 'Running' ? 'bg-[#dceeb1] text-[#1ea64a]' : 'bg-[#f7f7f5] text-[#999999]'
                      }`}>
                        {camp.status}
                      </span>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col gap-2">
                        <div className="flex justify-between text-[10px] text-[#999999] font-mono">
                          <span>{camp.completed} / {camp.total}</span>
                          <span>{camp.progress}%</span>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-[13px] text-black">{camp.conversion}</TableCell>
                    <TableCell className="px-4 py-2 text-right">
                      <span className="text-[11px] text-[#999999] italic">None</span>
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={6} className="h-32 px-6 text-center text-[13px] font-[320] italic text-[#999999]">
                    No campaigns yet.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  )
}
