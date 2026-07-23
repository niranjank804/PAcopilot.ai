"use client";

import {
  Activity,
  BarChart3,
  BookOpen,
  Database,
  LayoutDashboard,
  MessageSquare,
  Network,
  Rocket,
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
}

const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard, enabled: true },
  { label: "TM1 Connections", href: "/connections", icon: Database, enabled: true },
  { label: "AI Chat", href: "/chat", icon: MessageSquare, enabled: true },
  { label: "Knowledge Base", href: "/knowledge", icon: BookOpen, enabled: true },
  { label: "Metadata Explorer", href: "/metadata", icon: Network, enabled: true },
  { label: "Visualize", href: "/visualize", icon: BarChart3, enabled: true },
  { label: "Deployments", href: "/deployments", icon: Rocket, enabled: true },
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
