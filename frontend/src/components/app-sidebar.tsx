"use client";

import {
  Activity,
  BarChart3,
  BookOpen,
  Database,
  FileSpreadsheet,
  History,
  LayoutDashboard,
  MessageSquare,
  Network,
  Rocket,
  Ruler,
  Server,
  Settings,
  Users,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  enabled: boolean;
  /** Stable handle for the product tour. Deliberately not a class name
   * or a position: both change when someone restyles this list, and a
   * tour pinned to either points at nothing while still looking like it
   * works. A step whose handle is absent is skipped, so nav items that
   * a role cannot see simply drop out of the tour. */
  tour?: string;
}

const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard, enabled: true, tour: "nav-dashboard" },
  { label: "TM1 Connections", href: "/connections", icon: Database, enabled: true, tour: "nav-connections" },
  { label: "AI Chat", href: "/chat", icon: MessageSquare, enabled: true, tour: "nav-chat" },
  { label: "Knowledge Base", href: "/knowledge", icon: BookOpen, enabled: true, tour: "nav-knowledge" },
  { label: "Coding Standards", href: "/standards", icon: Ruler, enabled: true, tour: "nav-standards" },
  { label: "Metadata Explorer", href: "/metadata", icon: Network, enabled: true, tour: "nav-metadata" },
  { label: "Visualize", href: "/visualize", icon: BarChart3, enabled: true },
  { label: "Deployments", href: "/deployments", icon: Rocket, enabled: true, tour: "nav-deployments" },
  { label: "Reports", href: "/reports", icon: FileSpreadsheet, enabled: true },
  {
    label: "Report Workers",
    href: "/reports/workers",
    icon: Server,
    enabled: true,
  },
  {
    label: "Executions",
    href: "/reports/executions",
    icon: History,
    enabled: true,
  },
  { label: "Monitoring", href: "/monitoring", icon: Activity, enabled: true },
  { label: "Users", href: "/users", icon: Users, enabled: true },
  { label: "Settings", href: "/settings", icon: Settings, enabled: true },
];

export function AppSidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden w-64 shrink-0 border-r bg-background md:flex md:flex-col">
      <div className="flex h-14 items-center border-b px-6 text-sm font-semibold">
        PA-Copilot
      </div>
      <nav className="flex-1 space-y-1 p-3">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const isActive = pathname === item.href;

          if (!item.enabled) {
            return (
              <div
                key={item.href}
                title="Coming soon"
                className="flex cursor-not-allowed items-center gap-3 rounded-md px-3 py-2 text-sm text-muted-foreground/50"
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </div>
            );
          }

          return (
            <Link
              key={item.href}
              href={item.href}
              data-tour={item.tour}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground",
                isActive && "bg-accent text-accent-foreground",
              )}
            >
              <Icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
