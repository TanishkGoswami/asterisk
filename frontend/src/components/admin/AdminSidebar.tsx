import { Link, useLocation } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import {
  LayoutDashboard,
  Building2,
  AudioLines,
  Smartphone,
  Bot,
  History,
  PhoneCall,
  Receipt,
  Activity,
  Settings,
  ArrowLeft,
  Search,
  Layers,
  FileText,
} from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "../ui/sidebar";
import { supabase } from "@/lib/supabase";

interface SidebarItem {
  title: string;
  url: string;
  icon: any;
}

interface SidebarSection {
  label: string;
  items: SidebarItem[];
}

export function AdminSidebar() {
  const location = useLocation();
  const [profile, setProfile] = useState<any>(null);

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (session?.user) {
        supabase
          .from("profiles")
          .select("*")
          .eq("id", session.user.id)
          .single()
          .then(({ data }) => setProfile(data));
      }
    });
  }, []);

  const sections: SidebarSection[] = [
    {
      label: "SYSTEM",
      items: [
        { title: "Dashboard", url: "/admin", icon: LayoutDashboard },
        { title: "Live Calls", url: "/admin/live-calls", icon: AudioLines },
        { title: "Workspaces", url: "/admin/workspaces", icon: Building2 },
        { title: "SIP Trunks", url: "/admin/sip-trunks", icon: Smartphone },
        { title: "DID Numbers", url: "/admin/did-numbers", icon: PhoneCall },
      ],
    },
    {
      label: "OPERATIONS",
      items: [
        { title: "Call Admission", url: "/admin/call-admission", icon: Layers },
        { title: "Asterisk Configs", url: "/admin/asterisk-configs", icon: FileText },
        { title: "Provider Health", url: "/admin/providers", icon: Activity },
        { title: "Batch Campaigns", url: "/admin/batch-calls", icon: PhoneCall },
      ],
    },
    {
      label: "MANAGEMENT",
      items: [
        { title: "Agents", url: "/admin/agents", icon: Bot },
        { title: "Agent Playground", url: "/admin/qa", icon: Search },
        { title: "Call Logs", url: "/admin/calls", icon: History },
      ],
    },
    {
      label: "MONITORING",
      items: [
        { title: "Costs & Billing", url: "/admin/billing", icon: Receipt },
        { title: "System Health", url: "/admin/health", icon: Activity },
        { title: "Settings", url: "/admin/settings", icon: Settings },
      ],
    },
  ];

  return (
    <Sidebar className="border-r border-[#e6e6e6] bg-[#fcfcfb]">
      <SidebarHeader className="border-b border-[#e6e6e6] p-4 bg-white">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-[10px] bg-black text-[14px] font-semibold text-white">
            VP
          </div>
          <div className="flex flex-col">
            <span className="text-[14px] font-[500] text-black">VoicePilot</span>
            <span className="font-mono text-[10px] uppercase tracking-wider text-black/40">
              Super Admin
            </span>
          </div>
        </div>
      </SidebarHeader>

      <SidebarContent className="p-2">
        {sections.map((group, idx) => (
          <SidebarGroup key={idx} className="mb-2">
            <SidebarGroupLabel className="px-3 text-[10px] font-bold tracking-[0.15em] text-black/30">
              {group.label}
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {group.items.map((item, i) => {
                  const isActive = location.pathname === item.url;
                  return (
                    <SidebarMenuItem key={i}>
                      <SidebarMenuButton asChild>
                        <Link
                          to={item.url}
                          className={`flex items-center gap-3 rounded-[12px] px-3 py-2 text-[13px] font-[400] transition-all duration-150 ${
                            isActive
                              ? "bg-black text-white shadow-sm"
                              : "text-black/70 hover:bg-[#f2f2f0] hover:text-black"
                          }`}
                        >
                          <item.icon className="h-4 w-4" />
                          <span>{item.title}</span>
                        </Link>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  );
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>

      <SidebarFooter className="border-t border-[#e6e6e6] p-3 bg-white">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton asChild>
              <Link
                to="/dashboard"
                className="flex items-center gap-2 rounded-[12px] border border-[#e6e6e6] px-3 py-2 text-[12px] font-[500] text-black hover:bg-[#f7f7f5]"
              >
                <ArrowLeft className="h-3.5 w-3.5" />
                <span>Exit Admin Panel</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
