import { createFileRoute, Link } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { ArrowLeft, Info, PhoneCall, Bot, User, AudioLines, FileText, Activity, Loader2 } from 'lucide-react'
import { supabase } from "@/lib/supabase"

export const Route = createFileRoute('/_authenticated/dashboard/calls/$callId')({
  component: CallDetailsPage,
})

function formatDuration(seconds: number | null) {
  if (!seconds) return '0s'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

function formatTimestamp(ts: string) {
  return new Date(ts).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function statusBadgeClass(status: string) {
  if (!status) return 'bg-[#f1f1f1] text-[#999999]'
  const s = status.toLowerCase()
  if (s === 'completed') return 'bg-emerald-100 text-emerald-700'
  if (s === 'in_progress' || s === 'ringing') return 'bg-purple-100 text-purple-700'
  return 'bg-red-100 text-red-500'
}

function sentimentLabel(score: number | null) {
  if (score === null || score === undefined) return 'Neutral'
  if (score > 0.6) return 'Positive Sentiment'
  if (score < 0.4) return 'Negative Sentiment'
  return 'Neutral Sentiment'
}

function CallDetailsPage() {
  const { callId } = Route.useParams()
  const [call, setCall] = useState<any | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const apiUrl = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "")

  useEffect(() => {
    async function load() {
      try {
        const { data: { session } } = await supabase.auth.getSession()
        if (!session) return
        const headers = {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session.access_token}`,
          "ngrok-skip-browser-warning": "true",
        }
        const setupRes = await fetch(`${apiUrl}/api/v1/workspaces/setup`, {
          method: "POST",
          headers,
          body: JSON.stringify({ user_id: session.user.id, email: session.user.email }),
        })
        const { workspace_id } = await setupRes.json()
        const res = await fetch(`${apiUrl}/api/v1/workspaces/${workspace_id}/calls/${callId}`, { headers })
        if (!res.ok) throw new Error(`Call not found (${res.status})`)
        setCall(await res.json())
      } catch (e: any) {
        setError(e.message)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [callId, apiUrl])

  if (loading) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4">
        <Loader2 className="h-8 w-8 animate-spin text-[#c5b0f4]" />
        <p className="text-xs font-mono uppercase tracking-widest text-[#999999]">Loading call data...</p>
      </div>
    )
  }

  if (error || !call) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4">
        <p className="text-red-500 text-sm">{error || "Call not found"}</p>
        <Button asChild variant="outline" className="rounded-full">
          <Link to="/dashboard/calls">Back to calls</Link>
        </Button>
      </div>
    )
  }

  const transcript: any[] = call.transcript || []
  const latencyEntries = Object.values(call.metadata?.latency_by_sequence || {}) as any[]
  const avgLatency = latencyEntries.length > 0 
    ? Math.round(latencyEntries.reduce((sum, item) => sum + (item.total_perceived_ms || 0), 0) / latencyEntries.length)
    : null

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-8 px-4 py-4 md:px-5 md:py-5">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-6">
        <div className="space-y-4">
          <Button variant="ghost" className="h-8 w-8 rounded-full hover:bg-canvas-soft p-0" asChild>
            <Link to="/dashboard/calls">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">
              <FileText className="h-4 w-4" />
              <span>Interaction Report</span>
            </div>
            <h1 className="text-5xl font-display text-foreground">Call Review</h1>
            <p className="text-muted-foreground text-lg font-light italic">
              {call.caller_phone_number || 'Unknown caller'} • {formatTimestamp(call.created_at)}
            </p>
          </div>
        </div>
        <div className="flex gap-4">
          <Badge className={`h-10 px-4 rounded-full border-0 text-[10px] font-bold uppercase tracking-widest shadow-sm ${statusBadgeClass(call.status)}`}>
            {call.status}
          </Badge>
          <Badge variant="outline" className="h-10 px-4 rounded-full border-hairline bg-white text-[10px] font-bold uppercase tracking-widest text-muted-soft">
            {sentimentLabel(call.sentiment_score)}
          </Badge>
        </div>
      </div>

      <div className="grid gap-10 lg:grid-cols-7">
        <div className="lg:col-span-4 space-y-8">
          <div className="editorial-card overflow-hidden bg-white">
            <div className="p-8 border-b border-hairline flex items-center gap-2">
              <AudioLines className="h-4 w-4 text-muted-soft" />
              <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Full Transcript</span>
            </div>

            <div className="p-8 space-y-10 max-h-[700px] overflow-y-auto">
              {transcript.length === 0 ? (
                <p className="text-center text-[#999999] text-sm italic py-12">No transcript recorded for this call.</p>
              ) : (
                transcript.map((msg: any, i: number) => {
                  const isUser = msg.role === 'user'
                  return (
                    <div key={i} className={`flex gap-6 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
                      <div className={`h-12 w-12 rounded-2xl flex items-center justify-center shrink-0 border border-hairline ${isUser ? 'bg-canvas-soft text-muted-soft' : 'bg-primary/5 text-primary border-primary/10'}`}>
                        {isUser ? <User className="h-5 w-5" /> : <Bot className="h-5 w-5" />}
                      </div>
                      <div className={`flex flex-col gap-2 max-w-[85%] ${isUser ? 'items-end' : 'items-start'}`}>
                        <div className="flex items-center gap-3 text-[10px] font-bold uppercase tracking-widest text-muted-soft">
                          <span>{isUser ? 'Caller' : 'AI Agent'}</span>
                          {msg.started_at && (
                            <>
                              <span className="h-1 w-1 rounded-full bg-hairline" />
                              <span>{new Date(msg.started_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
                            </>
                          )}
                        </div>
                        <div className={`rounded-3xl p-6 text-sm leading-relaxed shadow-sm ${isUser ? 'bg-primary text-primary-foreground' : 'bg-canvas-soft text-foreground border border-hairline'}`}>
                          {msg.content}
                        </div>
                        {!isUser && call.metadata?.latency_by_sequence?.[String(msg.sequence_number)] && (() => {
                          const latencyObj = call.metadata.latency_by_sequence[String(msg.sequence_number)];
                          return (
                            <div className="flex flex-wrap items-center gap-1.5 mt-2 text-[9px] font-mono text-neutral-400">
                              <span className="bg-[#f7f7f5] rounded px-1.5 py-0.5 border border-neutral-200">STT EOT: {latencyObj.stt_eot_ms}ms</span>
                              <span className="bg-[#f7f7f5] rounded px-1.5 py-0.5 border border-neutral-200">LLM: {latencyObj.llm_first_token_ms}ms</span>
                              <span className="bg-[#f7f7f5] rounded px-1.5 py-0.5 border border-neutral-200">TTS: {latencyObj.tts_first_byte_ms}ms</span>
                              <span className="bg-emerald-50 text-emerald-700 font-bold rounded px-1.5 py-0.5 border border-emerald-100">
                                Total: {latencyObj.total_perceived_ms}ms
                              </span>
                            </div>
                          );
                        })()}
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </div>
        </div>

        <div className="lg:col-span-3 space-y-8">
          <div className="editorial-card p-8 bg-white space-y-8">
            <div className="flex items-center gap-2 pb-4 border-b border-hairline">
              <Info className="h-4 w-4 text-muted-soft" />
              <h3 className="text-xl font-display">Interaction Metadata</h3>
            </div>
            <div className="space-y-6">
              {[
                { label: 'Direction', value: call.direction, mono: true },
                { label: 'Caller', value: call.caller_phone_number || '—', mono: true },
                { label: 'Duration', value: formatDuration(call.actual_duration) },
                { label: 'Credits Charged', value: call.estimated_cost !== undefined && call.estimated_cost !== null ? `${parseFloat(call.estimated_cost).toFixed(2)}` : '0.00', mono: true },
                { label: 'Status', value: call.status },
              ].map((meta, i) => (
                <div key={i} className="flex justify-between items-center group">
                  <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">{meta.label}</span>
                  <span className={`text-sm font-medium text-foreground ${meta.mono ? 'font-mono' : ''}`}>{meta.value}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="editorial-card p-8 bg-white space-y-8">
            <div className="flex items-center gap-2 pb-4 border-b border-hairline">
              <Activity className="h-4 w-4 text-muted-soft" />
              <h3 className="text-xl font-display">Credit Breakdown</h3>
            </div>
            {call.usage ? (
              <div className="space-y-4">
                <div className="flex justify-between items-start text-xs border-b border-[#f7f7f5] pb-2">
                  <div className="flex flex-col">
                    <span className="font-semibold text-foreground">Speech-to-Text (STT)</span>
                    {call.usage.stt_audio_seconds !== undefined && call.usage.stt_audio_seconds !== null && (
                      <span className="text-[10px] text-muted-soft">{call.usage.stt_audio_seconds}s processed</span>
                    )}
                  </div>
                  <span className="font-mono font-medium text-foreground">
                    {call.usage.stt_cost_inr !== undefined && call.usage.stt_cost_inr !== null ? `${parseFloat(call.usage.stt_cost_inr).toFixed(4)}` : '0.0000'}
                  </span>
                </div>
                
                <div className="flex justify-between items-start text-xs border-b border-[#f7f7f5] pb-2">
                  <div className="flex flex-col">
                    <span className="font-semibold text-foreground">Language Model (LLM)</span>
                    {call.usage.llm_input_tokens !== undefined && call.usage.llm_input_tokens !== null && 
                     call.usage.llm_output_tokens !== undefined && call.usage.llm_output_tokens !== null && (
                      <span className="text-[10px] text-muted-soft">
                        {call.usage.llm_input_tokens} In / {call.usage.llm_output_tokens} Out
                      </span>
                    )}
                  </div>
                  <span className="font-mono font-medium text-foreground">
                    {call.usage.llm_cost_inr !== undefined && call.usage.llm_cost_inr !== null ? `${parseFloat(call.usage.llm_cost_inr).toFixed(4)}` : '0.0000'}
                  </span>
                </div>
                
                <div className="flex justify-between items-start text-xs border-b border-[#f7f7f5] pb-2">
                  <div className="flex flex-col">
                    <span className="font-semibold text-foreground">Text-to-Speech (TTS)</span>
                    {call.usage.tts_characters !== undefined && call.usage.tts_characters !== null && (
                      <span className="text-[10px] text-muted-soft">{call.usage.tts_characters} chars synthesized</span>
                    )}
                  </div>
                  <span className="font-mono font-medium text-foreground">
                    {call.usage.tts_cost_inr !== undefined && call.usage.tts_cost_inr !== null ? `${parseFloat(call.usage.tts_cost_inr).toFixed(4)}` : '0.0000'}
                  </span>
                </div>
                
                <div className="flex justify-between items-start text-xs border-b border-[#f7f7f5] pb-2">
                  <div className="flex flex-col">
                    <span className="font-semibold text-foreground">Telephony</span>
                    <span className="text-[10px] text-muted-soft">{formatDuration(call.actual_duration)} duration</span>
                  </div>
                  <span className="font-mono font-medium text-foreground">
                    {call.usage.telephony_cost_inr !== undefined && call.usage.telephony_cost_inr !== null ? `${parseFloat(call.usage.telephony_cost_inr).toFixed(4)}` : '0.0000'}
                  </span>
                </div>
                
                <div className="flex justify-between items-center font-bold text-sm pt-2">
                  <span>Total Credits</span>
                  <span className="font-mono text-[#c5b0f4] text-base">
                    {call.usage.credits_used !== undefined && call.usage.credits_used !== null ? `${parseFloat(call.usage.credits_used).toFixed(4)}` : '0.0000'}
                  </span>
                </div>
              </div>
            ) : (
              <p className="text-xs text-muted-soft italic leading-relaxed">
                Credit breakdown is currently unavailable or pending finalization.
              </p>
            )}
          </div>

          <div className="editorial-card p-8 bg-white space-y-8">
            <div className="flex items-center gap-2 pb-4 border-b border-hairline">
              <Activity className="h-4 w-4 text-muted-soft" />
              <h3 className="text-xl font-display">Technical Diagnostics</h3>
            </div>
            <div className="space-y-6">
              <div className="grid grid-cols-3 gap-4">
                <div className="p-4 rounded-xl bg-canvas-soft border border-hairline text-center">
                  <span className="text-[10px] font-bold uppercase tracking-widest text-muted-soft">Messages</span>
                  <p className="text-lg md:text-xl font-display mt-1">{transcript.length}</p>
                </div>
                <div className="p-4 rounded-xl bg-canvas-soft border border-hairline text-center">
                  <span className="text-[10px] font-bold uppercase tracking-widest text-muted-soft">Duration</span>
                  <p className="text-lg md:text-xl font-display mt-1">{formatDuration(call.actual_duration)}</p>
                </div>
                <div className="p-4 rounded-xl bg-canvas-soft border border-hairline text-center">
                  <span className="text-[10px] font-bold uppercase tracking-widest text-muted-soft">Avg Latency</span>
                  <p className="text-lg md:text-xl font-display mt-1">{avgLatency ? `${avgLatency}ms` : '—'}</p>
                </div>
              </div>
              {call.twilio_call_sid && (
                <div className="space-y-1">
                  <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Call SID</span>
                  <p className="text-xs font-mono text-[#999999] break-all">{call.twilio_call_sid}</p>
                </div>
              )}
            </div>
          </div>

          <div className="editorial-card p-8 bg-canvas-soft/30 border-dashed text-center space-y-4">
            <div className="flex justify-center">
              <div className="h-12 w-12 rounded-full bg-white border border-hairline flex items-center justify-center">
                <PhoneCall className="h-6 w-6 text-muted-soft opacity-40" />
              </div>
            </div>
            <p className="text-xs text-muted-foreground font-light italic leading-relaxed">
              {call.started_at
                ? `Call started at ${formatTimestamp(call.started_at)}${call.ended_at ? ` and ended at ${formatTimestamp(call.ended_at)}` : ''}.`
                : 'No timing data available for this call.'}
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
