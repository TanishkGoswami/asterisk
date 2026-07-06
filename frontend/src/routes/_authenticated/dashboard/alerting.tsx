import { createFileRoute } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { 
  Bell, 
  Plus, 
  Webhook, 
  Mail, 
  Slack,
  Settings2,
  AlertCircle
} from 'lucide-react'
import { useState } from 'react'

export const Route = createFileRoute('/_authenticated/dashboard/alerting')({
  component: AlertingPage,
})

function AlertingPage() {
  const [rules] = useState<any[]>([])

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-8 px-4 py-3 md:px-5 md:py-4">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-6">
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">
            <Bell className="h-4 w-4" />
            <span>Anomaly Detection</span>
            <Badge className="bg-[#c5b0f4] text-black hover:bg-[#c5b0f4] rounded-full text-[9px] px-2.5 py-0.5">BETA</Badge>
          </div>
          <h1 className="text-5xl font-display text-foreground">Alerting</h1>
          <p className="text-muted-foreground text-lg max-w-2xl font-light">
            Configure rules to get notified about interaction anomalies, latency spikes, and system events.
          </p>
        </div>
        <Button disabled className="h-14 bg-gray-100 text-gray-400 hover:bg-gray-100 rounded-full px-8 shrink-0 cursor-not-allowed">
          <Plus className="h-5 w-5 mr-2" />
          Create Rule (Beta)
        </Button>
      </div>

      {/* Beta status banner */}
      <div className="flex items-start gap-3 rounded-[16px] border border-[#c5b0f4]/30 bg-[#c5b0f4]/5 p-4 text-[#7c58c6]">
        <AlertCircle className="h-5 w-5 shrink-0 mt-0.5" />
        <div className="space-y-1">
          <p className="text-[14px] font-[500]">Alert Rules & Notification Channels are in Beta</p>
          <p className="text-[13px] opacity-80 font-[320] leading-relaxed">
            The alerting rules engine is currently undergoing backend testing. Real-time Slack, Email, and Webhook dispatching will be available in the upcoming release.
          </p>
        </div>
      </div>

      <div className="grid gap-8 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-white border border-[#e6e6e6] rounded-[24px] p-8 space-y-8 shadow-sm">
            <div className="flex items-center justify-between pb-4 border-b border-[#f1f1f1]">
               <h3 className="text-2xl font-display">Active Rules</h3>
               <Badge variant="outline" className="text-[10px] font-bold uppercase tracking-widest bg-gray-50">{rules.length} Configured</Badge>
            </div>
            
            <div className="space-y-4">
              {rules.length > 0 ? (
                rules.map((rule) => (
                  <div key={rule.id} className="flex items-center justify-between p-6 rounded-2xl border border-[#e6e6e6] bg-gray-50">
                    <div className="flex items-center gap-6">
                      <div className="h-12 w-12 rounded-xl flex items-center justify-center bg-gray-100">
                        <Bell className="h-5 w-5 text-gray-400" />
                      </div>
                      <div className="flex flex-col gap-1">
                        <span className="text-base font-bold text-gray-500">{rule.name}</span>
                      </div>
                    </div>
                  </div>
                ))
              ) : (
                <div className="flex flex-col items-center justify-center py-20 text-center space-y-4">
                  <div className="h-16 w-16 rounded-full bg-gray-50 flex items-center justify-center">
                    <Bell className="h-8 w-8 text-gray-300 opacity-50" />
                  </div>
                  <div className="space-y-1">
                    <h4 className="text-lg font-display text-gray-500">No Monitoring Rules</h4>
                    <p className="text-sm text-gray-400 font-light italic">Your system alerting triggers will appear here when connected.</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="space-y-8">
          <div className="bg-white border border-[#e6e6e6] rounded-[24px] p-8 space-y-8 shadow-sm">
            <div className="space-y-1">
               <h3 className="text-xl font-display">Output Channels</h3>
               <p className="text-xs text-muted-foreground font-light italic">Integrate where your team lives.</p>
            </div>
            
            <div className="space-y-4">
              {[
                { name: 'Slack', icon: Slack, status: 'Coming Soon', color: '#4A154B' },
                { name: 'Email', icon: Mail, status: 'Coming Soon', color: '#292524' },
                { name: 'Webhooks', icon: Webhook, status: 'Coming Soon', color: '#292524' },
              ].map((chan, i) => (
                <div key={i} className="flex items-center justify-between p-4 rounded-xl border border-[#e6e6e6] bg-gray-50/50">
                  <div className="flex items-center gap-4">
                    <div className="h-10 w-10 rounded-lg flex items-center justify-center bg-white border border-[#e6e6e6] shadow-sm">
                       <chan.icon className="h-5 w-5" style={{ color: chan.color, opacity: 0.3 }} />
                    </div>
                    <div className="flex flex-col">
                      <span className="text-sm font-bold text-gray-400">{chan.name}</span>
                      <span className="text-[10px] font-bold uppercase tracking-widest text-gray-400">{chan.status}</span>
                    </div>
                  </div>
                  <Button disabled variant="ghost" className="h-8 text-[10px] uppercase tracking-widest font-bold hover:bg-white text-gray-300">Configure</Button>
                </div>
              ))}
            </div>
            <Button disabled variant="outline" className="w-full h-12 border-[#e6e6e6] hover:bg-gray-50 gap-2 text-xs uppercase tracking-widest font-bold text-gray-400">
              <Plus className="h-4 w-4" />
              Register New Channel
            </Button>
          </div>

          <div className="bg-[#c5b0f4]/5 border border-[#c5b0f4]/15 rounded-[24px] p-6 shadow-sm">
             <div className="flex items-start gap-4">
                <Settings2 className="h-6 w-6 text-[#7c58c6] mt-1" />
                <div className="space-y-1">
                   <h4 className="text-sm font-bold uppercase tracking-widest text-[#7c58c6]">Intelligent Routing</h4>
                   <p className="text-xs text-[#7c58c6]/70 font-light leading-relaxed italic">Enable AI-driven alerting to automatically filter false positives based on sentiment and context.</p>
                </div>
             </div>
          </div>
        </div>
      </div>
    </div>
  )
}
