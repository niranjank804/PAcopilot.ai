"use client";

import {
  Activity,
  BarChart3,
  BellRing,
  BookOpen,
  Brain,
  Database,
  FileSpreadsheet,
  HeartPulse,
  History,
  LayoutDashboard,
  MessageSquare,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  Rocket,
  Ruler,
  Server,
  Settings,
  Users,
  UsersRound,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Tip } from "@/components/ui/tooltip";
import { useRememberedFlag } from "@/lib/use-remembered-flag";
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
        label: "Command Center",
        href: "/dashboard",
        icon: LayoutDashboard,
        tour: "nav-dashboard",
        help: "Everything that needs attention on the TM1 servers you can use: model health and its biggest risks, open incidents and alerts, failed and unusually slow processes, changes waiting for approval, recent deployments and model changes, and AI usage and cost.",
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
        label: "Team",
        href: "/team",
        icon: UsersRound,
        help: "Work items such as PBI #1234 with their whole story — investigation, root cause, fix, approval, deployment — plus conversations your colleagues shared and what changed on your TM1 servers.",
      },
      {
        label: "Engineering Memory",
        href: "/memory",
        icon: Brain,
        help: "What your team knows about the model that TM1 cannot say — run sequences, conventions, cautions, known issues. Approved entries go to the assistant in every conversation; its own suggestions wait for approval.",
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
        label: "Model Health",
        href: "/health",
        icon: HeartPulse,
        help: "A health score for the model with the evidence behind every point, and how long processes take: regressions, the slowest loads, and recent failures.",
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
        label: "Alerts",
        href: "/alerts",
        icon: BellRing,
        help: "Rules that watch your TM1 servers every 15 minutes — failed or unusually slow processes, dimension growth, security, model and deployment changes — and the alerts they raise. Rules only read; nothing is changed.",
      },
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

export function SidebarNav({
  onNavigate,
  collapsed = false,
}: {
  onNavigate?: () => void;
  /** Icons only: the label moves into the hover tip. */
  collapsed?: boolean;
}) {
  const pathname = usePathname();

  return (
    <nav className={cn("flex-1 overflow-y-auto py-4", collapsed ? "space-y-4 px-2" : "space-y-6 px-3")}>
      {NAV_GROUPS.map((group, index) => (
        <div key={group.label ?? index} className="space-y-1">
          {group.label && !collapsed ? (
            <p className="px-3 pb-1 text-[0.6875rem] font-semibold uppercase tracking-[0.06em] text-tertiary-foreground">
              {group.label}
            </p>
          ) : null}

          {group.items.map((item) => {
            const Icon = item.icon;
            const active = isActive(pathname, item.href);

            return (
              <div key={item.href}>
                <Tip content={collapsed ? `${item.label} — ${item.help}` : item.help} side="right">
                <Link
                  href={item.href}
                  data-tour={item.tour}
                  aria-current={active ? "page" : undefined}
                  aria-label={collapsed ? item.label : undefined}
                  onClick={onNavigate}
                  className={cn(
                    "flex items-center gap-3 rounded-lg py-2 text-sm transition-colors duration-150",
                    collapsed ? "justify-center px-0" : "px-3",
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
                  {collapsed ? null : <span className="truncate">{item.label}</span>}
                </Link>
                </Tip>

                {item.children && active && !collapsed ? (
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

export function SidebarBrand({ collapsed = false }: { collapsed?: boolean }) {
  return (
    <Link
      href="/dashboard"
      aria-label={collapsed ? "PA Copilot — overview" : undefined}
      className={cn(
        "flex h-14 shrink-0 items-center gap-2.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        collapsed ? "justify-center px-0" : "px-5",
      )}
    >
      <span
        className="flex size-6 items-center justify-center rounded-md bg-foreground text-[0.625rem] font-semibold tracking-tight text-background"
        aria-hidden
      >
        PA
      </span>
      {collapsed ? null : (
        <span className="text-[0.8125rem] font-semibold uppercase tracking-[0.08em]">
          Copilot
        </span>
      )}
    </Link>
  );
}

export function AppSidebar() {
  // Collapsed to icons, the page gets the width back — most wanted in the
  // assistant, where the conversation is the work.
  const [collapsed, setCollapsed] = useRememberedFlag("pa-copilot-sidebar-collapsed", false);
  const Toggle = collapsed ? PanelLeftOpen : PanelLeftClose;

  return (
    <aside
      className={cn(
        "hidden shrink-0 flex-col border-r border-border bg-sidebar transition-[width] duration-150 md:flex",
        collapsed ? "w-14" : "w-64",
      )}
    >
      {/* At the top, beside the logo: at the bottom it sat below the
          fold on a short window and behind the taskbar. */}
      <div className={cn("flex shrink-0 items-center", collapsed ? "flex-col" : "pr-2")}>
        <SidebarBrand collapsed={collapsed} />
        <Tip content={collapsed ? "Show the menu" : "Hide the menu to make room"} side="right">
          <button
            type="button"
            onClick={() => setCollapsed(!collapsed)}
            aria-label={collapsed ? "Expand menu" : "Collapse menu"}
            aria-expanded={!collapsed}
            className={cn(
              "flex size-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors duration-150",
              "hover:bg-secondary/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              collapsed ? "mb-1" : "ml-auto",
            )}
          >
            <Toggle className="size-4" aria-hidden />
          </button>
        </Tip>
      </div>
      <SidebarNav collapsed={collapsed} />
    </aside>
  );
}
