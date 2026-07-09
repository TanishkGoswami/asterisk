import { Link, useLocation, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import {
  LayoutDashboard,
  Bot,
  Book,
  Home,
  Smartphone,
  PhoneOutgoing,
  History,
  MessageSquare,
  PieChart,
  Search,
  Bell,
  Receipt,
  Settings,
  AudioLines,
  User,
  Calendar,
  Workflow,
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
  SidebarTrigger,
} from "../ui/sidebar";
import { supabase } from "@/lib/supabase";
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
  AlertDialogTrigger,
} from "../ui/alert-dialog";

export function AppSidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const [userName, setUserName] = useState("Loading...");
  const [userInitials, setUserInitials] = useState("--");
  const [logoutDialogOpen, setLogoutDialogOpen] = useState(false);

  useEffect(() => {
    const fetchUser = async () => {
      if (!supabase) return;
      try {
        const { data: { user } } = await supabase.auth.getUser();
        if (user) {
          const name = user.user_metadata?.full_name || user.email || "User";
          setUserName(name);
          const initials = name.split(" ").map((n: string) => n[0]).join("").substring(0, 2).toUpperCase();
          setUserInitials(initials);
        } else {
          setUserName("Guest");
          setUserInitials("G");
        }
      } catch (e) {
        console.error("Failed to fetch user:", e);
      }
    };
    fetchUser();
  }, []);

  const navGroups = [
    {
      label: "GENERAL",
      items: [
        { title: "Home", url: "/", icon: Home },
        { title: "Dashboard", url: "/dashboard", icon: Bot },
      ],
    },
    {
      label: "BUILD",
      items: [
        { title: "Agents", url: "/dashboard/agents", icon: Bot },
        { title: "Knowledge Base", url: "/dashboard/knowledge-base", icon: Book },
        { title: "Workflows", url: "/dashboard/workflows", icon: Workflow },
      ],
    },
    {
      label: "DEPLOY",
      items: [
        {
          title: "Phone Numbers",
          url: "/dashboard/phone-numbers",
          icon: Smartphone,
        },
        {
          title: "Batch Call",
          url: "/dashboard/batch-call",
          icon: PhoneOutgoing,
        },
        {
          title: "Schedules",
          url: "/dashboard/schedules",
          icon: Calendar,
        },
      ],
    },
    {
      label: "MONITOR",
      items: [
        { title: "Agent Playground", url: "/dashboard/playground", icon: Search },
        { title: "Call History", url: "/dashboard/calls", icon: History },
        {
          title: "Chat History",
          url: "/dashboard/chat-history",
          icon: MessageSquare,
        },
        { title: "Alerting", url: "/dashboard/alerting", icon: Bell },
      ],
    },
    {
      label: "SYSTEM",
      items: [
        {
          title: "Billing",
          url: "/dashboard/billing",
          icon: Receipt,
        },
        { title: "Settings", url: "/dashboard/settings", icon: Settings },
      ],
    },
  ];

  return (
    <Sidebar className="border-r border-[#e6e6e6] bg-[#f7f7f5] font-sans text-[#000000]">
      <SidebarHeader className="flex h-16 items-center border-b border-black/5 px-4 gap-4">
        <div className="flex items-center md:hidden">
          <SidebarTrigger className="h-9 w-9 text-black opacity-70 hover:opacity-100 transition-opacity" />
        </div>
        <Link to="/dashboard" className="flex items-center gap-2.5 text-black transition-opacity hover:opacity-80">
          <img src="/logo.png" alt="Logo" className="h-8 w-8 object-contain" />
          <span className="text-[17px] font-medium tracking-tight">VoicePilot</span>
        </Link>
      </SidebarHeader>
      <SidebarContent className="px-2 py-2 gap-1 overflow-y-auto [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden">
        {navGroups.map((group) => (
          <SidebarGroup key={group.label}>
            <SidebarGroupLabel className="mb-1 px-2 font-mono text-[10px] uppercase tracking-widest text-[#999999]">
              {group.label}
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu className="gap-0.5">
                {group.items.map((item) => {
                  const isActive =
                    item.url !== "#" && (
                    location.pathname === item.url ||
                    location.pathname.startsWith(item.url + "/"));

                  return (
                    <SidebarMenuItem key={item.title}>
                      <SidebarMenuButton
                        asChild
                        isActive={isActive}
                        className={`h-8 rounded-full px-3 transition-all duration-200 ${
                          isActive
                            ? "bg-[#ebebe9] text-black font-[480] border border-black/5 shadow-sm"
                            : "text-black/60 hover:bg-[#ebebe9] hover:text-black border border-transparent font-[330]"
                        }`}
                      >
                        <Link to={item.url} className="flex w-full items-center gap-2">
                          <item.icon className={`h-4 w-4 ${isActive ? "opacity-100" : "opacity-70"}`} strokeWidth={isActive ? 1.5 : 1.25} />
                          <span className={`text-[12px] ${isActive ? "font-[480]" : "font-[330]"}`}>{item.title}</span>
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
      <SidebarFooter className="border-t border-[#e6e6e6] p-3">
        <Link 
          to="/dashboard/profile"
          className="flex cursor-pointer items-center gap-2.5 rounded-lg border border-transparent px-2 py-2 transition-colors hover:bg-[#ebebe9]"
        >
          <div className="flex h-8 w-8 items-center justify-center rounded-full border border-[#e6e6e6] bg-white text-[12px] font-[480] tracking-tight shadow-sm">
            {userInitials}
          </div>
          <div className="flex flex-col">
            <span className="line-clamp-1 text-[13px] font-[480] leading-tight tracking-[-0.01em]">{userName}</span>
            <span className="mt-0.5 text-[11px] font-[330] text-[#666666]">metabull universe</span>
          </div>
        </Link>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
