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

import { Tip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  /** What this screen is for and how it works, shown on hover and on
   * keyboard focus. Written from what the code does today — the
   * capability registry is the source — not from a roadmap. */
  help: string;
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
        help: "AI runs, tool success rate, tokens and connection health for the last 30 days, plus your recent assistant sessions.",
      },
    ],
  },
  {
    label: "AI engineering",
    items: [
      {
        label: "AI Assistant",
        href: "/chat",
        icon: MessageSquare,
        tour: "nav-chat",
        help: "Ask about cubes, rules, TurboIntegrator and errors in plain English or by voice. Pick a specialist agent and it reads your live model with TM1 tools; any change it drafts waits for a person to deploy.",
      },
      {
        label: "Visualize",
        href: "/visualize",
        icon: BarChart3,
        help: "Turn a question into an MDX query and a chart from live cube data. Read-only.",
      },
      {
        label: "Knowledge Base",
        href: "/knowledge",
        icon: BookOpen,
        tour: "nav-knowledge",
        help: "Upload your own documentation so answers cite your material. Includes Explain Error: paste a TM1 error and get the cause and the fix.",
      },
      {
        label: "Coding Standards",
        href: "/standards",
        icon: Ruler,
        tour: "nav-standards",
        help: "Upload exported TI processes; PA-Copilot measures how your team writes TM1 and the agents follow it when they draft code.",
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
        help: "Register TM1 or Planning Analytics as a Service servers. Credentials are encrypted at rest; Test tells you which part is wrong if it cannot connect.",
      },
      {
        label: "Metadata Explorer",
        href: "/metadata",
        icon: Network,
        tour: "nav-metadata",
        help: "Browse cubes, dimensions, processes and chores, and trace what depends on what. Run Extract metadata once per connection to build the dependency graph.",
      },
      {
        label: "Deployments",
        href: "/deployments",
        icon: Rocket,
        tour: "nav-deployments",
        help: "Every rule or process change the assistant drafts lands here with impact analysis. Nothing reaches TM1 until someone with deploy rights executes it; the previous version is kept for rollback.",
      },
      {
        label: "Reports",
        href: "/reports",
        icon: FileSpreadsheet,
        help: "Developer preview. Refresh PAfE workbooks on a schedule through a Windows worker you run; outputs are stored as artifacts.",
        children: [
          {
            label: "Workers",
            href: "/reports/workers",
            icon: Server,
            help: "The Windows machines enrolled to run Excel refreshes, and whether each is online.",
          },
          {
            label: "Executions",
            href: "/reports/executions",
            icon: History,
            help: "Each report run, its status and its output files.",
          },
        ],
      },
    ],
  },
  {
    label: "Intelligence",
    items: [
      {
        label: "Monitoring",
        href: "/monitoring",
        icon: Activity,
        help: "AI usage by model, every TM1 tool call with its error rate, and the circuit-breaker state of each connection.",
      },
    ],
  },
  {
    label: "Admin",
    items: [
      {
        label: "Users",
        href: "/users",
        icon: Users,
        help: "Everyone in your organization, their role, and whether they are active. Roles decide who can deploy changes.",
      },
      {
        label: "Settings",
        href: "/settings",
        icon: Settings,
        help: "Your organization's name and plan.",
      },
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
                <Tip content={item.help} side="right">
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
                </Tip>

                {item.children && active ? (
                  <div className="mt-1 space-y-1 border-l border-border pl-3 ml-5">
                    {item.children.map((child) => (
                      <Tip key={child.href} content={child.help} side="right">
                      <Link
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
                      </Tip>
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
