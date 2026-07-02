import { createFileRoute } from '@tanstack/react-router'
import { useEffect, useState, useCallback } from 'react'
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs"
import {
  Plus, Shield, Info, Copy, Check, AlertTriangle, RefreshCw, Trash2, Eye, Server, Phone, CheckCircle2, XCircle, Edit, Globe, AudioLines
} from 'lucide-react'
import { supabase } from "@/lib/supabase"
import { toast } from "sonner"
import { useWorkspace } from "@/context/WorkspaceContext"

export const Route = createFileRoute('/_authenticated/dashboard/sip-trunks')({
  component: SIPTrunksPage,
})

export function SIPTrunksPage() {
  const { workspaceId: contextWsId, authHeaders: contextHeaders, loading: contextLoading } = useWorkspace()
  const [trunks, setTrunks] = useState<any[]>([])
  const [agents, setAgents] = useState<any[]>([])
  const [workspaceId, setWorkspaceId] = useState<string | null>(null)
  const [authHeaders, setAuthHeaders] = useState<Record<string, string> | null>(null)
  const [loading, setLoading] = useState(true)

  // Wizard state
  const [wizardOpen, setWizardOpen] = useState(false)
  const [wizardStep, setWizardStep] = useState(1)
  const [wizardData, setWizardData] = useState<any>({
    name: '',
    provider_type: 'custom',
    auth_type: 'ip_auth',
    sip_proxy: '',
    sip_port: 5060,
    transport: 'udp',
    username: '',
    password: '',
    provider_ips: '',
    allowed_codecs: ['ulaw', 'alaw'],
    outbound_caller_id: '',
    max_concurrent_calls: 10,
    // dids to add
    dids: []
  })
  const [didForm, setDidForm] = useState({
    phone_number: '',
    country_code: 'IN',
    label: '',
    agent_id: 'none',
    inbound_enabled: true,
    outbound_enabled: false,
    recording_enabled: false
  })
  
  // Detail state
  const [activeTrunk, setActiveTrunk] = useState<any | null>(null)
  const [trunkDids, setTrunkDids] = useState<any[]>([])
  const [generatedConfig, setGeneratedConfig] = useState<any>(null)
  const [validationResult, setValidationResult] = useState<any>(null)
  const [testResult, setTestResult] = useState<any>(null)
  const [copiedField, setCopiedField] = useState<string | null>(null)

  // DID management state
  const [addDidOpen, setAddDidOpen] = useState(false)
  const [addDidLoading, setAddDidLoading] = useState(false)
  const [addDidForm, setAddDidForm] = useState({
    phone_number: '',
    country_code: 'IN',
    label: '',
    agent_id: 'none',
    inbound_enabled: true,
    outbound_enabled: false,
    recording_enabled: false
  })
  const [editDidTarget, setEditDidTarget] = useState<any | null>(null)
  const [editDidLoading, setEditDidLoading] = useState(false)

  const apiUrl = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "")

  const fetchTrunks = useCallback(async (wsId: string, headers: Record<string, string>) => {
    try {
      const res = await fetch(`${apiUrl}/api/v1/workspaces/${wsId}/sip-trunks`, { headers })
      if (res.ok) {
        setTrunks(await res.json())
      }
    } catch (e) {
      console.error(e)
    }
  }, [apiUrl])

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
        // Fetch agents for routing select
        const agentRes = await fetch(`${apiUrl}/api/v1/workspaces/${contextWsId}/agents`, { headers: contextHeaders! })
        if (agentRes.ok) {
          setAgents(await agentRes.json())
        }
        
        await fetchTrunks(contextWsId!, contextHeaders!)
      } catch (err) {
        console.error("Failed to load page data:", err)
      } finally {
        setLoading(false)
      }
    }
    init()
  }, [contextWsId, contextHeaders, contextLoading, apiUrl, fetchTrunks])

  // Fetch specific details for active trunk
  const loadTrunkDetails = async (trunk: any) => {
    if (!workspaceId || !authHeaders) return
    setActiveTrunk(trunk)
    setGeneratedConfig(null)
    setValidationResult(null)
    setTestResult(null)
    
    try {
      // 1. Fetch DIDs
      const didsRes = await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/did-numbers`, { headers: authHeaders })
      if (didsRes.ok) {
        const allDids = await didsRes.json()
        setTrunkDids(allDids.filter((d: any) => d.sip_trunk_provider_id === trunk.id))
      }
      
      // 2. Fetch config
      const confRes = await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/sip-trunks/${trunk.id}/generate-asterisk-config`, {
        method: "POST",
        headers: authHeaders
      })
      if (confRes.ok) {
        setGeneratedConfig(await confRes.json())
      }
      
      // 3. Validate
      const valRes = await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/sip-trunks/${trunk.id}/validate`, {
        method: "POST",
        headers: authHeaders
      })
      if (valRes.ok) {
        setValidationResult(await valRes.json())
      }
    } catch (e) {
      toast.error("Failed to load trunk details")
    }
  }

  // Trigger test
  const triggerTest = async (trunkId: string) => {
    if (!workspaceId || !authHeaders) return
    toast.info("Running network check and DNS resolve...")
    try {
      const res = await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/sip-trunks/${trunkId}/test`, {
        method: "POST",
        headers: authHeaders
      })
      if (res.ok) {
        const result = await res.json()
        setTestResult(result)
        toast.success(result.status === "success" ? "Test completed successfully!" : "Trunk tests failed.")
        // Refresh trunk list status
        await fetchTrunks(workspaceId, authHeaders)
        if (activeTrunk && activeTrunk.id === trunkId) {
          const updated = trunks.find(t => t.id === trunkId)
          if (updated) {
            setActiveTrunk({ ...activeTrunk, status: updated.status, last_checked_at: updated.last_checked_at })
          }
        }
      }
    } catch (e) {
      toast.error("Trunk test failed")
    }
  }

  // Handle trunk creation wizard submit
  const handleWizardSubmit = async () => {
    if (!workspaceId || !authHeaders) return

    // Validations
    if (!wizardData.name || wizardData.name.trim().length < 3) {
      toast.error("Trunk name must be at least 3 characters")
      return
    }
    const domainRegex = /^([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])(\.([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9]))*$/
    const ipRegex = /^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$/
    if (!wizardData.sip_proxy || (!domainRegex.test(wizardData.sip_proxy) && !ipRegex.test(wizardData.sip_proxy))) {
      toast.error("SIP proxy must be a valid domain name or IP address")
      return
    }
    if (wizardData.auth_type === 'username_password') {
      if (!wizardData.username || wizardData.username.trim() === '') {
        toast.error("SIP Username is required")
        return
      }
      if (!wizardData.password || wizardData.password.trim() === '') {
        toast.error("SIP Password is required")
        return
      }
    }
    if (wizardData.auth_type === 'ip_auth') {
      if (!wizardData.provider_ips || wizardData.provider_ips.trim() === '') {
        toast.error("Authorized provider IPs are required for IP Authentication")
        return
      }
      const ips = wizardData.provider_ips.split(',').map((ip: string) => ip.trim())
      for (const ip of ips) {
        if (!ipRegex.test(ip)) {
          toast.error(`Invalid IP address: ${ip}`)
          return
        }
      }
    }

    try {
      const providerIpsArray = wizardData.provider_ips
        ? wizardData.provider_ips.split(',').map((ip: string) => ip.trim())
        : []
      
      const trunkPayload = {
        name: wizardData.name,
        provider_type: wizardData.provider_type,
        auth_type: wizardData.auth_type,
        sip_proxy: wizardData.sip_proxy,
        sip_port: parseInt(wizardData.sip_port),
        transport: wizardData.transport,
        username: wizardData.auth_type === 'username_password' ? wizardData.username : null,
        password: wizardData.auth_type === 'username_password' ? wizardData.password : null,
        provider_ips: providerIpsArray,
        allowed_codecs: wizardData.allowed_codecs,
        outbound_caller_id: wizardData.outbound_caller_id || null,
        max_concurrent_calls: parseInt(wizardData.max_concurrent_calls)
      }


      const res = await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/sip-trunks`, {
        method: "POST",
        headers: authHeaders,
        body: JSON.stringify(trunkPayload)
      })

      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || "Failed to create SIP Trunk")
      }

      const createdTrunk = await res.json()

      // 2. Create and link DIDs if any
      for (const did of wizardData.dids) {
        await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/did-numbers`, {
          method: "POST",
          headers: authHeaders,
          body: JSON.stringify({
            phone_number: did.phone_number,
            country_code: did.country_code,
            label: did.label,
            sip_trunk_provider_id: createdTrunk.id,
            agent_id: did.agent_id === 'none' ? null : did.agent_id,
            inbound_enabled: did.inbound_enabled,
            outbound_enabled: did.outbound_enabled,
            recording_enabled: did.recording_enabled
          })
        })
      }

      toast.success("SIP Trunk and DIDs registered successfully!")
      setWizardOpen(false)
      setWizardStep(1)
      setWizardData({
        name: '',
        provider_type: 'custom',
        auth_type: 'ip_auth',
        sip_proxy: '',
        sip_port: 5060,
        transport: 'udp',
        username: '',
        password: '',
        provider_ips: '',
        allowed_codecs: ['ulaw', 'alaw'],
        outbound_caller_id: '',
        max_concurrent_calls: 10,
        dids: []
      })
      await fetchTrunks(workspaceId, authHeaders)
    } catch (e: any) {
      toast.error(e.message || "Failed to complete trunk setup")
    }
  }

  // Toggle soft disable
  const toggleTrunkStatus = async (trunk: any) => {
    if (!workspaceId || !authHeaders) return
    const targetStatus = trunk.status === 'disabled' ? 'pending' : 'disabled'
    try {
      const res = await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/sip-trunks/${trunk.id}`, {
        method: "PATCH",
        headers: authHeaders,
        body: JSON.stringify({ status: targetStatus })
      })
      if (res.ok) {
        toast.success(`Trunk ${targetStatus === 'disabled' ? 'disabled' : 'enabled'} successfully`)
        await fetchTrunks(workspaceId, authHeaders)
        if (activeTrunk && activeTrunk.id === trunk.id) {
          setActiveTrunk({ ...activeTrunk, status: targetStatus })
        }
      }
    } catch (e) {
      toast.error("Failed to modify trunk status")
    }
  }

  const handleCopy = (text: string, field: string) => {
    navigator.clipboard.writeText(text)
    setCopiedField(field)
    toast.success("Copied to clipboard")
    setTimeout(() => setCopiedField(null), 2000)
  }

  const handleAddDid = async () => {
    if (!workspaceId || !authHeaders || !activeTrunk) return
    if (!addDidForm.phone_number.trim()) {
      toast.error("Phone number is required")
      return
    }
    setAddDidLoading(true)
    try {
      const payload = {
        phone_number: addDidForm.phone_number.trim(),
        country_code: addDidForm.country_code,
        label: addDidForm.label.trim() || null,
        sip_trunk_provider_id: activeTrunk.id,
        agent_id: addDidForm.agent_id === 'none' ? null : addDidForm.agent_id,
        inbound_enabled: addDidForm.inbound_enabled,
        outbound_enabled: addDidForm.outbound_enabled,
        recording_enabled: addDidForm.recording_enabled
      }
      const res = await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/did-numbers`, {
        method: "POST",
        headers: authHeaders,
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || "Failed to add DID number")
      }
      setAddDidOpen(false)
      setAddDidForm({
        phone_number: '',
        country_code: 'IN',
        label: '',
        agent_id: 'none',
        inbound_enabled: true,
        outbound_enabled: false,
        recording_enabled: false
      })
      
      // reload DIDs
      const didsRes = await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/did-numbers`, { headers: authHeaders })
      if (didsRes.ok) {
        const allDids = await didsRes.json()
        setTrunkDids(allDids.filter((d: any) => d.sip_trunk_provider_id === activeTrunk.id))
      }
      toast.success("DID number added successfully")
    } catch (err: any) {
      toast.error(err.message)
    } finally {
      setAddDidLoading(false)
    }
  }

  const handleEditDid = async () => {
    if (!workspaceId || !authHeaders || !editDidTarget || !activeTrunk) return
    setEditDidLoading(true)
    try {
      const payload = {
        label: editDidTarget.label?.trim() || null,
        agent_id: editDidTarget.agent_id === 'none' || editDidTarget.agent_id === null ? null : editDidTarget.agent_id,
      }
      const res = await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/did-numbers/${editDidTarget.id}`, {
        method: "PATCH",
        headers: authHeaders,
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || "Failed to update DID number")
      }
      setEditDidTarget(null)
      
      // reload DIDs
      const didsRes = await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/did-numbers`, { headers: authHeaders })
      if (didsRes.ok) {
        const allDids = await didsRes.json()
        setTrunkDids(allDids.filter((d: any) => d.sip_trunk_provider_id === activeTrunk.id))
      }
      toast.success("DID number updated successfully")
    } catch (err: any) {
      toast.error(err.message)
    } finally {
      setEditDidLoading(false)
    }
  }

  const handleDeleteDid = async (didId: string) => {
    if (!workspaceId || !authHeaders || !activeTrunk) return
    if (!confirm("Are you sure you want to delete this DID number?")) return
    try {
      const res = await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/did-numbers/${didId}`, {
        method: "DELETE",
        headers: authHeaders
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || "Failed to delete DID number")
      }
      
      // reload DIDs
      const didsRes = await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/did-numbers`, { headers: authHeaders })
      if (didsRes.ok) {
        const allDids = await didsRes.json()
        setTrunkDids(allDids.filter((d: any) => d.sip_trunk_provider_id === activeTrunk.id))
      }
      toast.success("DID number deleted successfully")
    } catch (err: any) {
      toast.error(err.message)
    }
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-8 px-4 py-3 md:px-5 md:py-4">
      <div className="space-y-8">
        
        {/* Header */}
        <div className="flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
          <div className="space-y-3">
            <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-[#999999]">
              <AudioLines className="h-3.5 w-3.5" />
              <span>Telephony Settings</span>
            </div>
            <h1 className="text-4xl font-[340] tracking-[-0.03em] text-black md:text-5xl">
              SIP Trunks
            </h1>
            <p className="max-w-2xl text-[15px] font-[330] leading-relaxed text-black/60">
              Manage custom SIP trunks, register DID numbers, configure pjsip endpoints, and map inbound routes to your AI Agents.
            </p>
          </div>
          <Button
            onClick={() => { setWizardOpen(true); setWizardStep(1) }}
            className="h-9 shrink-0 rounded-full bg-[#c5b0f4] px-5 text-[13px] font-[480] text-black transition-all duration-200 hover:bg-[#c5b0f4]/90"
          >
            <Plus className="mr-2 h-4 w-4" />
            Add SIP Trunk
          </Button>
        </div>

        {loading ? (
          <div className="h-64 flex flex-col items-center justify-center space-y-4">
            <RefreshCw className="h-8 w-8 animate-spin text-[#c5b0f4]" />
            <p className="text-xs font-mono uppercase tracking-widest text-neutral-400">Loading SIP Trunks...</p>
          </div>
        ) : trunks.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-[20px] border border-dashed border-[#e6e6e6] bg-white p-12 text-center">
            <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-full border border-[#e6e6e6] bg-[#f7f7f5] shadow-sm">
              <Server className="h-8 w-8 text-[#999999]" strokeWidth={1.5} />
            </div>
            <h3 className="mb-3 text-[20px] font-[450] text-black">No SIP Trunks configured</h3>
            <p className="mb-8 max-w-[420px] text-[14px] font-[320] leading-relaxed text-[#666666]">
              Add custom SIP connectivity from Jio, Airtel, Twilio or Exotel to route local calls to your Voice AI system.
            </p>
            <Button
              onClick={() => { setWizardOpen(true); setWizardStep(1) }}
              className="h-10 rounded-full bg-[#c5b0f4] px-7 text-[13px] font-[480] text-black hover:bg-[#c5b0f4]/90"
            >
              Configure SIP Trunk
            </Button>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            
            {/* Sidebar List */}
            <div className="lg:col-span-1 space-y-4">
              <div className="font-mono text-xs uppercase tracking-wider text-neutral-400 px-1">SIP Providers</div>
              <div className="space-y-2">
                {trunks.map((t) => {
                  const isActive = activeTrunk?.id === t.id
                  return (
                    <div
                      key={t.id}
                      onClick={() => loadTrunkDetails(t)}
                      className={`cursor-pointer rounded-2xl border p-4 transition-all duration-200 ${
                        isActive
                          ? "border-black bg-[#f7f7f5] shadow-sm"
                          : "border-[#e6e6e6] bg-white hover:bg-[#f7f7f5]/40"
                      }`}
                    >
                      <div className="flex items-start justify-between">
                        <div>
                          <h4 className="font-medium text-sm text-black">{t.name}</h4>
                          <p className="text-xs text-neutral-500 font-mono mt-0.5">{t.sip_proxy}</p>
                        </div>
                        <span className={`rounded-full px-2 py-0.5 text-[9px] font-mono uppercase tracking-[0.05em] ${
                          t.status === 'active' ? 'bg-[#dceeb1] text-[#1ea64a]' :
                          t.status === 'error' ? 'bg-red-100 text-red-600' : 'bg-neutral-100 text-neutral-500'
                        }`}>
                          {t.status}
                        </span>
                      </div>
                      <div className="flex items-center justify-between mt-3 text-xs text-neutral-400 border-t border-black/5 pt-2">
                        <span>{t.provider_type.toUpperCase()}</span>
                        <span>{t.auth_type === 'ip_auth' ? 'IP Auth' : 'User/Pass'}</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Main Detail Area */}
            <div className="lg:col-span-2">
              {activeTrunk ? (
                <div className="rounded-[24px] border border-[#e6e6e6] bg-white p-6 shadow-sm space-y-6">
                  
                  {/* Active Trunk Banner */}
                  <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between border-b border-black/5 pb-5">
                    <div>
                      <h2 className="text-2xl font-[450] tracking-tight">{activeTrunk.name}</h2>
                      <p className="text-sm text-neutral-500 font-mono mt-0.5">{activeTrunk.sip_proxy}:{activeTrunk.sip_port} ({activeTrunk.transport})</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        variant="outline"
                        onClick={() => triggerTest(activeTrunk.id)}
                        className="h-8 rounded-full text-xs"
                      >
                        <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
                        Run Test
                      </Button>
                      <Button
                        variant="outline"
                        onClick={() => toggleTrunkStatus(activeTrunk)}
                        className="h-8 rounded-full text-xs text-neutral-700 hover:text-black"
                      >
                        {activeTrunk.status === 'disabled' ? 'Enable' : 'Disable'}
                      </Button>
                    </div>
                  </div>

                  <Tabs defaultValue="overview" className="w-full">
                    <TabsList className="mb-4 bg-[#f7f7f5] rounded-full p-1 border border-black/5">
                      <TabsTrigger value="overview" className="rounded-full px-4 py-1 text-xs">Overview</TabsTrigger>
                      <TabsTrigger value="dids" className="rounded-full px-4 py-1 text-xs">DID Numbers</TabsTrigger>
                      <TabsTrigger value="config" className="rounded-full px-4 py-1 text-xs">Asterisk Config</TabsTrigger>
                      <TabsTrigger value="results" className="rounded-full px-4 py-1 text-xs">Validation & Tests</TabsTrigger>
                      <TabsTrigger value="settings" className="rounded-full px-4 py-1 text-xs">Settings</TabsTrigger>
                    </TabsList>

                    <TabsContent value="overview" className="space-y-4">
                      <div className="grid grid-cols-2 gap-4">
                        <div className="rounded-xl bg-[#f7f7f5] p-3 border border-black/5">
                          <Label className="text-[10px] font-mono text-neutral-400 uppercase">Provider Type</Label>
                          <div className="text-sm font-medium mt-0.5 uppercase">{activeTrunk.provider_type}</div>
                        </div>
                        <div className="rounded-xl bg-[#f7f7f5] p-3 border border-black/5">
                          <Label className="text-[10px] font-mono text-neutral-400 uppercase">Auth Type</Label>
                          <div className="text-sm font-medium mt-0.5 uppercase">{activeTrunk.auth_type === 'ip_auth' ? 'IP Authentication' : 'Username / Password'}</div>
                        </div>
                        <div className="rounded-xl bg-[#f7f7f5] p-3 border border-black/5 col-span-2">
                          <Label className="text-[10px] font-mono text-neutral-400 uppercase">Allowed Codecs</Label>
                          <div className="text-sm font-medium mt-0.5 font-mono">{(activeTrunk.allowed_codecs || []).join(', ')}</div>
                        </div>
                        {activeTrunk.auth_type === 'ip_auth' && (
                          <div className="rounded-xl bg-[#f7f7f5] p-3 border border-black/5 col-span-2">
                            <Label className="text-[10px] font-mono text-neutral-400 uppercase">Authorized IP Addresses</Label>
                            <div className="text-sm font-medium mt-0.5 font-mono">
                              {(activeTrunk.provider_ips || []).map((ip: string) => <div key={ip}>{ip}</div>)}
                            </div>
                          </div>
                        )}
                        {activeTrunk.auth_type === 'username_password' && (
                          <div className="rounded-xl bg-[#f7f7f5] p-3 border border-black/5 col-span-2">
                            <Label className="text-[10px] font-mono text-neutral-400 uppercase">Username / SIP Auth ID</Label>
                            <div className="text-sm font-medium mt-0.5 font-mono">{activeTrunk.username}</div>
                          </div>
                        )}
                      </div>
                    </TabsContent>

                    <TabsContent value="dids" className="space-y-4">
                      <div className="flex justify-between items-center">
                        <Label className="text-xs font-mono text-neutral-400 uppercase">Configured DID Numbers</Label>
                        <Button
                          variant="outline"
                          onClick={() => {
                            setAddDidForm({
                              phone_number: '',
                              country_code: 'IN',
                              label: '',
                              agent_id: 'none',
                              inbound_enabled: true,
                              outbound_enabled: false,
                              recording_enabled: false
                            });
                            setAddDidOpen(true);
                          }}
                          className="h-8 rounded-full text-xs"
                        >
                          <Plus className="mr-1.5 h-3.5 w-3.5" />
                          Add DID
                        </Button>
                      </div>

                      {trunkDids.length === 0 ? (
                        <div className="text-center py-8 border border-dashed border-black/10 rounded-2xl">
                          <Phone className="h-6 w-6 text-neutral-300 mx-auto mb-2" />
                          <p className="text-xs text-neutral-500">No active DID numbers map to this SIP Trunk yet.</p>
                        </div>
                      ) : (
                        <div className="border border-black/5 rounded-2xl overflow-hidden divide-y divide-black/5">
                          {trunkDids.map((d) => (
                            <div key={d.id} className="flex items-center justify-between p-3.5 hover:bg-neutral-50">
                              <div>
                                <div className="text-sm font-mono font-medium">{d.phone_number}</div>
                                <div className="text-[11px] text-neutral-400">{d.label || "No label"} · {d.country_code}</div>
                              </div>
                              <div className="flex items-center gap-3">
                                {d.agents ? (
                                  <span className="text-[11px] bg-[#c5b0f4]/10 text-[#c5b0f4] border border-[#c5b0f4]/20 px-2 py-0.5 rounded-full font-medium">
                                    Agent: {d.agents.name}
                                  </span>
                                ) : (
                                  <span className="text-[10px] font-mono text-neutral-300 uppercase tracking-wider">Unlinked</span>
                                )}
                                <div className="flex items-center gap-1.5">
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    onClick={() => {
                                      setEditDidTarget({
                                        id: d.id,
                                        phone_number: d.phone_number,
                                        label: d.label || '',
                                        agent_id: d.agent_id || 'none'
                                      });
                                    }}
                                    className="h-7 w-7 text-neutral-500 hover:text-black hover:bg-black/5 rounded-full"
                                  >
                                    <Edit className="h-3.5 w-3.5" />
                                  </Button>
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    onClick={() => handleDeleteDid(d.id)}
                                    className="h-7 w-7 text-red-500 hover:text-red-700 hover:bg-red-50 rounded-full"
                                  >
                                    <Trash2 className="h-3.5 w-3.5" />
                                  </Button>
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </TabsContent>

                    <TabsContent value="config" className="space-y-4">
                      {generatedConfig ? (
                        <div className="space-y-4">
                          <div className="rounded-xl bg-black p-4 text-white font-mono text-xs overflow-x-auto relative">
                            <div className="flex justify-between items-center mb-2 text-neutral-400 border-b border-white/10 pb-1">
                              <span>pjsip.conf configuration block</span>
                              <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => handleCopy(generatedConfig.pjsip_conf, 'pjsip')}
                                className="h-6 w-6 text-white hover:bg-white/10"
                              >
                                {copiedField === 'pjsip' ? <Check className="h-3 w-3 text-green-400" /> : <Copy className="h-3 w-3" />}
                              </Button>
                            </div>
                            <pre className="text-left whitespace-pre-wrap">{generatedConfig.pjsip_conf}</pre>
                          </div>

                          <div className="rounded-xl bg-black p-4 text-white font-mono text-xs overflow-x-auto relative">
                            <div className="flex justify-between items-center mb-2 text-neutral-400 border-b border-white/10 pb-1">
                              <span>extensions.conf dialplan block</span>
                              <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => handleCopy(generatedConfig.extensions_conf, 'ext')}
                                className="h-6 w-6 text-white hover:bg-white/10"
                              >
                                {copiedField === 'ext' ? <Check className="h-3 w-3 text-green-400" /> : <Copy className="h-3 w-3" />}
                              </Button>
                            </div>
                            <pre className="text-left whitespace-pre-wrap">{generatedConfig.extensions_conf}</pre>
                          </div>

                          <div className="rounded-xl bg-neutral-900 p-4 text-white font-mono text-xs overflow-x-auto relative">
                            <div className="flex justify-between items-center mb-2 text-neutral-400 border-b border-white/10 pb-1">
                              <span>Firewall Setup Commands (suggestions)</span>
                              <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => handleCopy(generatedConfig.firewall_commands, 'fw')}
                                className="h-6 w-6 text-white hover:bg-white/10"
                              >
                                {copiedField === 'fw' ? <Check className="h-3 w-3 text-green-400" /> : <Copy className="h-3 w-3" />}
                              </Button>
                            </div>
                            <pre className="text-left whitespace-pre-wrap">{generatedConfig.firewall_commands}</pre>
                          </div>
                        </div>
                      ) : (
                        <div className="text-center py-6 text-xs text-neutral-400">Loading configurations...</div>
                      )}
                    </TabsContent>

                    <TabsContent value="results" className="space-y-4">
                      {/* Validation warnings */}
                      {validationResult && (
                        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 space-y-2">
                          <div className="flex items-center gap-2 text-amber-800 font-medium text-sm">
                            <AlertTriangle className="h-4 w-4" />
                            <span>Configuration Validation Check</span>
                          </div>
                          {validationResult.warnings.length === 0 ? (
                            <p className="text-xs text-amber-700">No integration warnings. Setup looks correct.</p>
                          ) : (
                            <ul className="list-disc pl-4 space-y-1 text-xs text-amber-700">
                              {validationResult.warnings.map((w: string, i: number) => <li key={i}>{w}</li>)}
                            </ul>
                          )}
                        </div>
                      )}

                      {/* Test connection results */}
                      {testResult ? (
                        <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4 space-y-3">
                          <div className="flex items-center justify-between border-b border-black/5 pb-2">
                            <span className="text-sm font-medium">Latest Test Result</span>
                            <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full ${
                              testResult.status === 'success' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                            }`}>{testResult.status.toUpperCase()}</span>
                          </div>
                          <div className="space-y-2 text-xs">
                            <div className="flex items-center justify-between">
                              <span className="text-neutral-500">SIP Proxy DNS Lookup</span>
                              {testResult.result?.dns_resolved ? <CheckCircle2 className="h-4 w-4 text-green-500" /> : <XCircle className="h-4 w-4 text-red-500" />}
                            </div>
                            <div className="flex items-center justify-between">
                              <span className="text-neutral-500">AudioSocket Server Status (Local 9092)</span>
                              {testResult.result?.audiosocket_running ? <CheckCircle2 className="h-4 w-4 text-green-500" /> : <XCircle className="h-4 w-4 text-amber-500" />}
                            </div>
                            {testResult.error && (
                              <div className="text-red-500 text-[11px] font-mono mt-2 pt-2 border-t border-black/5">
                                Error detail: {testResult.error}
                              </div>
                            )}
                          </div>
                        </div>
                      ) : (
                        <div className="text-center py-6 text-xs text-neutral-400">Run a test to verify connectivity.</div>
                      )}
                    </TabsContent>

                    <TabsContent value="settings" className="space-y-4 animate-in fade-in duration-500">
                      <div className="space-y-4 max-w-xl">
                        <div className="grid grid-cols-2 gap-4">
                          <div className="space-y-1.5 col-span-2">
                            <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">Trunk Name</Label>
                            <Input
                              value={activeTrunk.name}
                              onChange={(e) => setActiveTrunk({ ...activeTrunk, name: e.target.value })}
                              className="h-11 rounded-xl"
                            />
                          </div>
                          <div className="space-y-1.5 col-span-2">
                            <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">SIP Server / Proxy Hostname</Label>
                            <Input
                              value={activeTrunk.sip_proxy}
                              onChange={(e) => setActiveTrunk({ ...activeTrunk, sip_proxy: e.target.value })}
                              className="h-11 rounded-xl font-mono text-sm"
                            />
                          </div>
                          <div className="space-y-1.5">
                            <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">Port</Label>
                            <Input
                              type="number"
                              value={activeTrunk.sip_port}
                              onChange={(e) => setActiveTrunk({ ...activeTrunk, sip_port: parseInt(e.target.value) || 5060 })}
                              className="h-11 rounded-xl font-mono"
                            />
                          </div>
                          <div className="space-y-1.5">
                            <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">Max Concurrent Calls</Label>
                            <Input
                              type="number"
                              value={activeTrunk.max_concurrent_calls}
                              onChange={(e) => setActiveTrunk({ ...activeTrunk, max_concurrent_calls: parseInt(e.target.value) || 10 })}
                              className="h-11 rounded-xl font-mono"
                            />
                          </div>
                          {activeTrunk.auth_type === 'ip_auth' ? (
                            <div className="space-y-1.5 col-span-2">
                              <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">Authorized Provider IPs (comma separated)</Label>
                              <Input
                                value={Array.isArray(activeTrunk.provider_ips) ? activeTrunk.provider_ips.join(', ') : (activeTrunk.provider_ips || '')}
                                onChange={(e) => setActiveTrunk({ ...activeTrunk, provider_ips: e.target.value })}
                                className="h-11 rounded-xl font-mono text-sm"
                              />
                            </div>
                          ) : (
                            <>
                              <div className="space-y-1.5">
                                <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">SIP Username</Label>
                                <Input
                                  value={activeTrunk.username || ''}
                                  onChange={(e) => setActiveTrunk({ ...activeTrunk, username: e.target.value })}
                                  className="h-11 rounded-xl font-mono"
                                />
                              </div>
                              <div className="space-y-1.5">
                                <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">New Password (leave empty to keep current)</Label>
                                <Input
                                  type="password"
                                  placeholder="••••••••"
                                  value={activeTrunk.newPassword || ''}
                                  onChange={(e) => setActiveTrunk({ ...activeTrunk, newPassword: e.target.value })}
                                  className="h-11 rounded-xl font-mono"
                                />
                              </div>
                            </>
                          )}
                          <div className="space-y-1.5 col-span-2">
                            <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">Outbound Caller ID (optional)</Label>
                            <Input
                              value={activeTrunk.outbound_caller_id || ''}
                              onChange={(e) => setActiveTrunk({ ...activeTrunk, outbound_caller_id: e.target.value })}
                              className="h-11 rounded-xl font-mono"
                            />
                          </div>
                        </div>
                        <Button
                          onClick={async () => {
                            if (!workspaceId || !authHeaders || !activeTrunk) return

                            // Validations
                            if (!activeTrunk.name || activeTrunk.name.trim().length < 3) {
                              toast.error("Trunk name must be at least 3 characters")
                              return
                            }
                            const domainRegex = /^([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])(\.([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9]))*$/
                            const ipRegex = /^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$/
                            if (!activeTrunk.sip_proxy || (!domainRegex.test(activeTrunk.sip_proxy) && !ipRegex.test(activeTrunk.sip_proxy))) {
                              toast.error("SIP proxy must be a valid domain name or IP address")
                              return
                            }
                            if (activeTrunk.auth_type === 'username_password') {
                              if (!activeTrunk.username || activeTrunk.username.trim() === '') {
                                toast.error("SIP Username is required")
                                return
                              }
                            }
                            if (activeTrunk.auth_type === 'ip_auth') {
                              const rawIps = typeof activeTrunk.provider_ips === 'string'
                                ? activeTrunk.provider_ips
                                : (Array.isArray(activeTrunk.provider_ips) ? activeTrunk.provider_ips.join(', ') : '')
                              if (!rawIps || rawIps.trim() === '') {
                                toast.error("Authorized provider IPs are required for IP Authentication")
                                return
                              }
                              const ips = rawIps.split(',').map((ip: string) => ip.trim())
                              for (const ip of ips) {
                                if (!ipRegex.test(ip)) {
                                  toast.error(`Invalid IP address: ${ip}`)
                                  return
                                }
                              }
                            }

                            try {
                              const providerIpsVal = activeTrunk.auth_type === 'ip_auth'
                                ? (typeof activeTrunk.provider_ips === 'string'
                                    ? activeTrunk.provider_ips.split(',').map((ip: string) => ip.trim())
                                    : activeTrunk.provider_ips)
                                : []
                              const res = await fetch(`${apiUrl}/api/v1/workspaces/${workspaceId}/sip-trunks/${activeTrunk.id}`, {
                                method: "PATCH",
                                headers: authHeaders,
                                body: JSON.stringify({
                                  name: activeTrunk.name,
                                  sip_proxy: activeTrunk.sip_proxy,
                                  sip_port: activeTrunk.sip_port,
                                  transport: activeTrunk.transport,
                                  username: activeTrunk.username || null,
                                  password: activeTrunk.newPassword || undefined,
                                  provider_ips: providerIpsVal,
                                  max_concurrent_calls: activeTrunk.max_concurrent_calls,
                                  outbound_caller_id: activeTrunk.outbound_caller_id || null
                                })
                              })
                              if (res.ok) {
                                toast.success("SIP Trunk updated successfully!")
                                const updated = await res.json()
                                setActiveTrunk(updated)
                                await fetchTrunks(workspaceId, authHeaders)
                              } else {
                                const err = await res.json()
                                toast.error(err.detail || "Failed to update trunk settings")
                              }
                            } catch (err) {
                              toast.error("Failed to update trunk settings")
                            }
                          }}
                          className="h-10 rounded-full bg-[#c5b0f4] text-black hover:bg-[#c5b0f4]/90 px-6 mt-4"
                        >
                          Save Changes
                        </Button>
                      </div>
                    </TabsContent>
                  </Tabs>

                </div>
              ) : (
                <div className="h-64 flex flex-col items-center justify-center border border-dashed border-[#e6e6e6] rounded-[24px] bg-[#f7f7f5]/40 text-center">
                  <Info className="h-6 w-6 text-neutral-300 mb-2" />
                  <p className="text-sm text-neutral-500 font-[320]">Select a SIP trunk provider from the list to view config, route DIDs, and run validation tests.</p>
                </div>
              )}
            </div>

          </div>
        )}

        {/* Wizard Add SIP Trunk Dialog */}
        <Dialog open={wizardOpen} onOpenChange={setWizardOpen}>
          <DialogContent className="max-w-xl rounded-3xl">
            <DialogHeader>
              <DialogTitle className="text-2xl font-[450] tracking-tight">Add SIP Trunk Provider</DialogTitle>
              <div className="flex justify-between items-center text-xs text-neutral-400 font-mono mt-1 border-b border-black/5 pb-2">
                <span>Step {wizardStep} of 4</span>
                <span>{wizardStep === 1 ? 'Select Provider' : wizardStep === 2 ? 'Details & Credentials' : wizardStep === 3 ? 'DID Configuration' : 'Summary & Install'}</span>
              </div>
            </DialogHeader>

            {/* STEP 1: Select Provider */}
            {wizardStep === 1 && (
              <div className="py-4 space-y-4">
                <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">Select Carrier Provider</Label>
                <div className="grid grid-cols-3 gap-3">
                  {[
                    { id: 'airtel', label: 'Airtel' },
                    { id: 'jio', label: 'Jio' },
                    { id: 'tata', label: 'Tata' },
                    { id: 'twilio', label: 'Twilio Elastic' },
                    { id: 'exotel', label: 'Exotel' },
                    { id: 'myoperator', label: 'MyOperator' },
                    { id: 'knowlarity', label: 'Knowlarity' },
                    { id: 'custom', label: 'Custom Carrier' }
                  ].map((p) => (
                    <div
                      key={p.id}
                      onClick={() => setWizardData({ ...wizardData, provider_type: p.id, name: p.label + " Trunk" })}
                      className={`cursor-pointer border rounded-2xl p-4 text-center transition-all ${
                        wizardData.provider_type === p.id ? 'border-black bg-neutral-50 shadow-sm font-medium' : 'border-neutral-200 hover:bg-neutral-50/50'
                      }`}
                    >
                      <div className="text-sm">{p.label}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* STEP 2: Credentials and details */}
            {wizardStep === 2 && (
              <div className="py-4 space-y-4 max-h-[400px] overflow-y-auto pr-2">
                <div className="grid grid-cols-2 gap-4">
                  <div className="col-span-2 space-y-1.5">
                    <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">Trunk Connection Name</Label>
                    <Input
                      placeholder="My Airtel SIP Trunk"
                      value={wizardData.name}
                      onChange={(e) => setWizardData({ ...wizardData, name: e.target.value })}
                      className="h-11 rounded-xl"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">Authentication Protocol</Label>
                    <Select
                      value={wizardData.auth_type}
                      onValueChange={(val) => setWizardData({ ...wizardData, auth_type: val })}
                    >
                      <SelectTrigger className="h-11 rounded-xl">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="rounded-xl">
                        <SelectItem value="ip_auth">IP Authentication (White-list)</SelectItem>
                        <SelectItem value="username_password">Username / SIP Password</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">Transport</Label>
                    <Select
                      value={wizardData.transport}
                      onValueChange={(val) => setWizardData({ ...wizardData, transport: val })}
                    >
                      <SelectTrigger className="h-11 rounded-xl">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="rounded-xl">
                        <SelectItem value="udp">UDP</SelectItem>
                        <SelectItem value="tcp">TCP</SelectItem>
                        <SelectItem value="tls">TLS (Secure)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-1.5 col-span-2">
                    <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">SIP Server / Proxy Hostname</Label>
                    <Input
                      placeholder="sip.airtel.in or 10.12.1.20"
                      value={wizardData.sip_proxy}
                      onChange={(e) => setWizardData({ ...wizardData, sip_proxy: e.target.value })}
                      className="h-11 rounded-xl font-mono text-sm"
                    />
                  </div>

                  <div className="space-y-1.5">
                    <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">Port</Label>
                    <Input
                      type="number"
                      value={wizardData.sip_port}
                      onChange={(e) => setWizardData({ ...wizardData, sip_port: parseInt(e.target.value) || 5060 })}
                      className="h-11 rounded-xl font-mono"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">Max Concurrent Calls</Label>
                    <Input
                      type="number"
                      value={wizardData.max_concurrent_calls}
                      onChange={(e) => setWizardData({ ...wizardData, max_concurrent_calls: parseInt(e.target.value) || 10 })}
                      className="h-11 rounded-xl font-mono"
                    />
                  </div>

                  {wizardData.auth_type === 'ip_auth' ? (
                    <div className="space-y-1.5 col-span-2">
                      <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">Authorized Provider IPs (comma separated)</Label>
                      <Input
                        placeholder="10.12.1.25, 10.12.1.26"
                        value={wizardData.provider_ips}
                        onChange={(e) => setWizardData({ ...wizardData, provider_ips: e.target.value })}
                        className="h-11 rounded-xl font-mono text-sm"
                      />
                    </div>
                  ) : (
                    <>
                      <div className="space-y-1.5">
                        <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">SIP Username / Auth ID</Label>
                        <Input
                          placeholder="username"
                          value={wizardData.username}
                          onChange={(e) => setWizardData({ ...wizardData, username: e.target.value })}
                          className="h-11 rounded-xl font-mono"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">SIP Password</Label>
                        <Input
                          type="password"
                          placeholder="••••••••"
                          value={wizardData.password}
                          onChange={(e) => setWizardData({ ...wizardData, password: e.target.value })}
                          className="h-11 rounded-xl font-mono"
                        />
                      </div>
                    </>
                  )}

                  <div className="space-y-1.5 col-span-2">
                    <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">Outbound Caller ID (optional)</Label>
                    <Input
                      placeholder="+911140002000"
                      value={wizardData.outbound_caller_id}
                      onChange={(e) => setWizardData({ ...wizardData, outbound_caller_id: e.target.value })}
                      className="h-11 rounded-xl font-mono"
                    />
                  </div>
                </div>
              </div>
            )}

            {/* STEP 3: Add DID Numbers */}
            {wizardStep === 3 && (
              <div className="py-4 space-y-4">
                <div className="border border-black/5 rounded-2xl p-4 bg-neutral-50 space-y-3">
                  <div className="text-xs font-mono uppercase tracking-widest text-neutral-400">Add a DID Number</div>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <Label className="text-[10px] font-mono uppercase tracking-wider text-neutral-400">Phone Number (E.164)</Label>
                      <Input
                        placeholder="+911140001000"
                        value={didForm.phone_number}
                        onChange={(e) => setDidForm({ ...didForm, phone_number: e.target.value })}
                        className="h-10 rounded-xl font-mono text-sm bg-white"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-[10px] font-mono uppercase tracking-wider text-neutral-400">Friendly Label</Label>
                      <Input
                        placeholder="Inbound Support line"
                        value={didForm.label}
                        onChange={(e) => setDidForm({ ...didForm, label: e.target.value })}
                        className="h-10 rounded-xl bg-white"
                      />
                    </div>
                    <div className="space-y-1 col-span-2">
                      <Label className="text-[10px] font-mono uppercase tracking-wider text-neutral-400">Map to AI Agent</Label>
                      <Select
                        value={didForm.agent_id}
                        onValueChange={(val) => setDidForm({ ...didForm, agent_id: val })}
                      >
                        <SelectTrigger className="h-10 rounded-xl bg-white">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="rounded-xl">
                          <SelectItem value="none">— Unlinked (no routing) —</SelectItem>
                          {agents.map((a) => (
                            <SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                  <Button
                    onClick={() => {
                      if (!didForm.phone_number) { toast.error("Number is required"); return }
                      setWizardData({
                        ...wizardData,
                        dids: [...wizardData.dids, { ...didForm }]
                      })
                      setDidForm({
                        phone_number: '',
                        country_code: 'IN',
                        label: '',
                        agent_id: 'none',
                        inbound_enabled: true,
                        outbound_enabled: false,
                        recording_enabled: false
                      })
                    }}
                    className="h-8 rounded-full bg-white border text-xs text-black shadow-sm mt-2"
                  >
                    Add to Trunk Connection
                  </Button>
                </div>

                <div className="space-y-2">
                  <div className="text-xs font-mono text-neutral-400 uppercase tracking-widest">Linked Numbers List</div>
                  {wizardData.dids.length === 0 ? (
                    <div className="text-center py-4 border rounded-2xl text-xs text-neutral-400">No DIDs configured. You can add them later too.</div>
                  ) : (
                    <div className="border border-black/5 rounded-xl divide-y divide-black/5">
                      {wizardData.dids.map((d: any, idx: number) => {
                        const agentName = agents.find(a => a.id === d.agent_id)?.name || 'Unlinked'
                        return (
                          <div key={idx} className="flex justify-between items-center p-2.5 text-xs">
                            <div>
                              <span className="font-mono font-medium">{d.phone_number}</span>
                              <span className="text-neutral-400 font-mono ml-2">({d.label || 'No Label'})</span>
                            </div>
                            <div className="flex items-center gap-3">
                              <span className="bg-[#c5b0f4]/10 text-[#c5b0f4] px-2 py-0.5 rounded-full border border-[#c5b0f4]/15">
                                {agentName}
                              </span>
                              <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => {
                                  const filtered = wizardData.dids.filter((_: any, i: number) => i !== idx)
                                  setWizardData({ ...wizardData, dids: filtered })
                                }}
                                className="h-5 w-5 text-red-500"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* STEP 4: Review and submit */}
            {wizardStep === 4 && (
              <div className="py-4 space-y-4 text-sm max-h-[400px] overflow-y-auto pr-2">
                <div className="rounded-2xl border p-4 bg-[#f7f7f5]/40 space-y-2.5">
                  <div className="flex justify-between">
                    <span className="text-neutral-400 font-mono text-xs">Name:</span>
                    <span className="font-medium">{wizardData.name}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-neutral-400 font-mono text-xs">SIP Proxy:</span>
                    <span className="font-mono">{wizardData.sip_proxy}:{wizardData.sip_port}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-neutral-400 font-mono text-xs">Auth Protocol:</span>
                    <span className="font-mono">{wizardData.auth_type.toUpperCase()}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-neutral-400 font-mono text-xs">DIDs to Link:</span>
                    <span className="font-mono">{wizardData.dids.length}</span>
                  </div>
                </div>

                <div className="rounded-2xl border border-amber-200 bg-amber-50/50 p-4 flex gap-3">
                  <Shield className="h-5 w-5 text-amber-500 shrink-0 mt-0.5" />
                  <div className="space-y-1">
                    <div className="text-xs font-semibold text-amber-900">Asterisk Integration Required</div>
                    <p className="text-[11px] text-amber-800 leading-relaxed">
                      After creation, you will need to copy the generated PJSIP configurations and dialplan blocks into your VPS `/etc/asterisk/pjsip.conf` and `/etc/asterisk/extensions.conf` respectively, then reload Asterisk.
                    </p>
                  </div>
                </div>
              </div>
            )}

            <DialogFooter className="flex justify-between items-center sm:justify-between">
              <div>
                {wizardStep > 1 && (
                  <Button
                    variant="outline"
                    onClick={() => setWizardStep(wizardStep - 1)}
                    className="rounded-full h-10 px-5 text-xs"
                  >
                    Back
                  </Button>
                )}
              </div>
              <div className="flex gap-2">
                <Button
                  variant="ghost"
                  onClick={() => setWizardOpen(false)}
                  className="rounded-full h-10 px-5 text-xs"
                >
                  Cancel
                </Button>
                 {wizardStep < 4 ? (
                   <Button
                     onClick={() => {
                       if (wizardStep === 2) {
                         if (!wizardData.name || wizardData.name.trim().length < 3) {
                           toast.error("Trunk name must be at least 3 characters")
                           return
                         }
                         const domainRegex = /^([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])(\.([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9]))*$/
                         const ipRegex = /^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$/
                         if (!wizardData.sip_proxy || (!domainRegex.test(wizardData.sip_proxy) && !ipRegex.test(wizardData.sip_proxy))) {
                           toast.error("SIP proxy must be a valid domain name or IP address")
                           return
                         }
                         if (wizardData.auth_type === 'username_password') {
                           if (!wizardData.username || wizardData.username.trim() === '') {
                             toast.error("SIP Username is required")
                             return
                           }
                           if (!wizardData.password || wizardData.password.trim() === '') {
                             toast.error("SIP Password is required")
                             return
                           }
                         }
                         if (wizardData.auth_type === 'ip_auth') {
                           if (!wizardData.provider_ips || wizardData.provider_ips.trim() === '') {
                             toast.error("Authorized provider IPs are required for IP Authentication")
                             return
                           }
                           const ips = wizardData.provider_ips.split(',').map((ip: string) => ip.trim())
                           for (const ip of ips) {
                             if (!ipRegex.test(ip)) {
                               toast.error(`Invalid IP address: ${ip}`)
                               return
                             }
                           }
                         }
                       }
                       setWizardStep(wizardStep + 1)
                     }}
                    className="rounded-full h-10 px-5 text-xs bg-[#c5b0f4] text-black hover:bg-[#c5b0f4]/90"
                  >
                    Next
                  </Button>
                ) : (
                  <Button
                    onClick={handleWizardSubmit}
                    className="rounded-full h-10 px-6 text-xs bg-[#c5b0f4] text-black hover:bg-[#c5b0f4]/90 font-medium"
                  >
                    Save & Finish
                  </Button>
                )}
              </div>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* Add DID Dialog */}
        <Dialog open={addDidOpen} onOpenChange={setAddDidOpen}>
          <DialogContent className="max-w-md rounded-3xl">
            <DialogHeader>
              <DialogTitle className="text-xl font-[450] tracking-tight">Add DID Number to {activeTrunk?.name}</DialogTitle>
            </DialogHeader>
            <div className="py-4 space-y-4">
              <div className="space-y-1.5">
                <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">Phone Number (E.164 format)</Label>
                <Input
                  placeholder="+919343418163"
                  value={addDidForm.phone_number}
                  onChange={(e) => setAddDidForm({ ...addDidForm, phone_number: e.target.value })}
                  className="h-11 rounded-xl font-mono text-sm"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">Friendly Label</Label>
                <Input
                  placeholder="My Custom SIP Line"
                  value={addDidForm.label}
                  onChange={(e) => setAddDidForm({ ...addDidForm, label: e.target.value })}
                  className="h-11 rounded-xl text-sm"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">Country Code</Label>
                <Input
                  placeholder="IN"
                  value={addDidForm.country_code}
                  onChange={(e) => setAddDidForm({ ...addDidForm, country_code: e.target.value })}
                  className="h-11 rounded-xl font-mono text-sm"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">Map to AI Agent</Label>
                <Select
                  value={addDidForm.agent_id}
                  onValueChange={(val) => setAddDidForm({ ...addDidForm, agent_id: val })}
                >
                  <SelectTrigger className="h-11 rounded-xl text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="rounded-xl">
                    <SelectItem value="none">— Unlinked (no routing) —</SelectItem>
                    {agents.map((a) => (
                      <SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <DialogFooter className="flex gap-2">
              <Button
                variant="ghost"
                onClick={() => setAddDidOpen(false)}
                className="rounded-full h-10 px-5 text-xs"
              >
                Cancel
              </Button>
              <Button
                onClick={handleAddDid}
                disabled={addDidLoading}
                className="rounded-full h-10 px-5 text-xs bg-[#c5b0f4] text-black hover:bg-[#c5b0f4]/90"
              >
                {addDidLoading ? "Adding..." : "Add DID"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* Edit DID Dialog */}
        <Dialog open={!!editDidTarget} onOpenChange={(open) => !open && setEditDidTarget(null)}>
          <DialogContent className="max-w-md rounded-3xl">
            <DialogHeader>
              <DialogTitle className="text-xl font-[450] tracking-tight">Edit DID: {editDidTarget?.phone_number}</DialogTitle>
            </DialogHeader>
            <div className="py-4 space-y-4">
              <div className="space-y-1.5">
                <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">Friendly Label</Label>
                <Input
                  placeholder="My Custom SIP Line"
                  value={editDidTarget?.label || ''}
                  onChange={(e) => setEditDidTarget({ ...editDidTarget, label: e.target.value })}
                  className="h-11 rounded-xl text-sm"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-[11px] font-mono uppercase tracking-widest text-[#999999]">Map to AI Agent</Label>
                <Select
                  value={editDidTarget?.agent_id || 'none'}
                  onValueChange={(val) => setEditDidTarget({ ...editDidTarget, agent_id: val })}
                >
                  <SelectTrigger className="h-11 rounded-xl text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="rounded-xl">
                    <SelectItem value="none">— Unlinked (no routing) —</SelectItem>
                    {agents.map((a) => (
                      <SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <DialogFooter className="flex gap-2">
              <Button
                variant="ghost"
                onClick={() => setEditDidTarget(null)}
                className="rounded-full h-10 px-5 text-xs"
              >
                Cancel
              </Button>
              <Button
                onClick={handleEditDid}
                disabled={editDidLoading}
                className="rounded-full h-10 px-5 text-xs bg-[#c5b0f4] text-black hover:bg-[#c5b0f4]/90"
              >
                {editDidLoading ? "Saving..." : "Save Changes"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

      </div>
    </div>
  )
}
