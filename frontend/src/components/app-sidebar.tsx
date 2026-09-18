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
  /** Stable handle for the product tour. Deliberately not a class name
   * or a position: both change when someone restyles this list, and a
   * tour pinned to either points at nothing while still looking like it
   * works. A step whose handle is absent is skipped, so nav items that
   * a role cannot see simply drop out of the tour. */
  tour?: string;
  /** Shown only while the user is inside this section, so the first
   * level of navigation stays short. */
  children?: NavItem[];
}

interface NavGroup {
  /** Omitted for the first group: a label above a single Overview link
   * is noise. */
  label?: string;
  items: NavItem[];
}

/**
 * Grouped by the job being done, not by the order features were built.
 *
 * A TM1 engineer arrives with one of four intents — ask the assistant
 * something, work on the model, check how the platform is running, or
 * administer it — and the grouping is those four. Every route the app
 * has is still reachable; the reporting sub-pages fold under Reports so
 * the top level stays readable.
 */
const NAV_GROUPS: NavGroup[] = [
  {
    items: [
      {
        label: "Overview",
        href: "/dashboard",
        icon: LayoutDashboard,
        tour: "nav-dashboard",
      },
    ],
  },
  {
    label: "AI engineering",
    items: [
      { label: "AI Assistant", href: "/chat", icon: MessageSquare, tour: "nav-chat" },
      { label: "Visualize", href: "/visualize", icon: BarChart3 },
      {
        label: "Knowledge Base",
        href: "/knowledge",
        icon: BookOpen,
        tour: "nav-knowledge",
      },
      {
        label: "Coding Standards",
        href: "/standards",
        icon: Ruler,
        tour: "nav-standards",
      },
    ],
  },
  {
    label: "TM1",
    items: [
      {
        label: "Connections",
        href: "/connections",
        icon: Database,
        tour: "nav-connections",
      },
      {
        label: "Metadata Explorer",
        href: "/metadata",
        icon: Network,
        tour: "nav-metadata",
      },
      {
        label: "Deployments",
        href: "/deployments",
        icon: Rocket,
        tour: "nav-deployments",
      },
      {
        label: "Reports",
        href: "/reports",
        icon: FileSpreadsheet,
        children: [
          { label: "Workers", href: "/reports/workers", icon: Server },
          { label: "Executions", href: "/reports/executions", icon: History },
        ],
      },
    ],
  },
  {
    label: "Intelligence",
    items: [{ label: "Monitoring", href: "/monitoring", icon: Activity }],
  },
  {
    label: "Admin",
    items: [
      { label: "Users", href: "/users", icon: Users },
      { label: "Settings", href: "/settings", icon: Settings },
    ],
  },
];

/** Every nav destination, flattened — used to title the current page. */
export const NAV_DESTINATIONS = NAV_GROUPS.flatMap((group) =>
  group.items.flatMap((item) => [item, ...(item.children ?? [])]),
).map(({ label, href }) => ({ label, href }));

function isActive(pathname: string, href: string): boolean {
  // Prefix match, so a connection's detail page keeps Connections lit —
  // an exact match left the whole sidebar looking unselected as soon as
  // anyone opened a record.
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();

  return (
    <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-4">
      {NAV_GROUPS.map((group, index) => (
        <div key={group.label ?? index} className="space-y-1">
          {group.label ? (
            <p className="px-3 pb-1 text-[0.6875rem] font-semibold uppercase tracking-[0.06em] text-tertiary-foreground">
              {group.label}
            </p>
          ) : null}

          {group.items.map((item) => {
            const Icon = item.icon;
            const active = isActive(pathname, item.href);

            return (
              <div key={item.href}>
                <Link
                  href={item.href}
                  data-tour={item.tour}
                  aria-current={active ? "page" : undefined}
                  onClick={onNavigate}
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors duration-150",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    active
                      ? "bg-secondary font-medium text-foreground"
                      : "font-normal text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
                  )}
                >
                  <Icon
                    className={cn(
                      "size-4 shrink-0",
                      active ? "text-primary" : "text-tertiary-foreground",
                    )}
                    aria-hidden
                  />
                  <span className="truncate">{item.label}</span>
                </Link>

                {item.children && active ? (
                  <div className="mt-1 space-y-1 border-l border-border pl-3 ml-5">
                    {item.children.map((child) => (
                      <Link
                        key={child.href}
                        href={child.href}
                        onClick={onNavigate}
                        aria-current={
                          isActive(pathname, child.href) ? "page" : undefined
                        }
                        className={cn(
                          "block rounded-lg px-3 py-1.5 text-[0.8125rem] transition-colors duration-150",
                          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          isActive(pathname, child.href)
                            ? "font-medium text-foreground"
                            : "text-muted-foreground hover:text-foreground",
                        )}
                      >
                        {child.label}
                      </Link>
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      ))}
    </nav>
  );
}

export function SidebarBrand() {
  return (
    <Link
      href="/dashboard"
      className="flex h-14 shrink-0 items-center gap-2.5 px-5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span
        className="flex size-6 items-center justify-center rounded-md bg-foreground text-[0.625rem] font-semibold tracking-tight text-background"
        aria-hidden
      >
        PA
      </span>
      <span className="text-[0.8125rem] font-semibold uppercase tracking-[0.08em]">
        Copilot
      </span>
    </Link>
  );
}

export function AppSidebar() {
  return (
    <aside className="hidden w-64 shrink-0 flex-col border-r border-border bg-sidebar md:flex">
      <SidebarBrand />
      <SidebarNav />
    </aside>
  );
}
