"use client";

import { useQuery } from "@tanstack/react-query";
import { BellRing, HeartPulse, Rocket, Siren, Timer, TriangleAlert } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { EnvironmentBadge } from "@/components/environment-badge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiRequest } from "@/lib/api-client";
import { changeHref, when } from "@/lib/team";
import type { Environment } from "@/lib/types";
import { cn } from "@/lib/utils";

interface Server {
  connection_id: string;
  connection_name: string;
  environment: Environment;
}

interface ChangeRow extends Server {
  id: string;
  change_type: string;
  target_name: string;
  status: string;
  created_at: string;
  executed_at: string | null;
  rolled_back_at: string | null;
  by: string | null;
}

export interface CommandCenterData {
  servers: number;
  health: (Server & { score: number; grade: string; scanned_at: string })[];
  risks: { category: string; label: string; count: number; points: number; servers: string[] }[];
  incidents: { id: string; reference: string; title: string; severity: string | null; status: string }[];
  failed_processes: (Server & { process: string; failed_runs_7_days: number; last_failed_at: string })[];
  regressions: (Server & { process: string; summary: string })[];
  alerts: { open: number; critical: number; latest: (Server & { id: string; title: string; severity: string })[] };
  pending_approvals: ChangeRow[];
  deployments: ChangeRow[];
  model_changes: (Server & { at: string; counts: Record<string, number> })[];
  ai: { days: number; requests: number; cost_usd: number; avg_latency_ms: number };
}

function Section({
  title,
  description,
  icon,
  href,
  count,
  urgent,
  tour,
  children,
}: {
  title: string;
  description: string;
  icon: ReactNode;
  href: string;
  count: number;
  urgent?: boolean;
  /** `data-tour` target for the page's feature tour. */
  tour?: string;
  children: ReactNode;
}) {
  return (
    <Card data-tour={tour}>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            {icon}
            <Link href={href} className="hover:underline">
              {title}
            </Link>
          </CardTitle>
          <CardDescription>{description}</CardDescription>
        </div>
        <Badge variant={count && urgent ? "destructive" : count ? "warning" : "outline"}>{count}</Badge>
      </CardHeader>
      <CardContent className="text-sm">{children}</CardContent>
    </Card>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="text-muted-foreground">{children}</p>;
}

/**
 * What needs attention across the TM1 servers this person may use: one
 * read of what PA-Copilot has recorded, so it is instant and never waits on
 * a slow server.
 */
export function CommandCenter() {
  const query = useQuery({
    queryKey: ["command-center"],
    queryFn: () => apiRequest<CommandCenterData>("/command-center"),
    refetchInterval: 120_000,
  });

  if (query.isPending) return <Skeleton className="h-72 w-full" />;
  if (query.isError) {
    return <p className="text-sm text-destructive">The command center could not be loaded.</p>;
  }
  const d = query.data;

  if (!d.servers) {
    return (
      <Card data-tour="dashboard-setup">
        <CardHeader>
          <CardTitle className="text-base">Command center</CardTitle>
          <CardDescription>
            Connect a TM1 server on the <Link href="/connections" className="underline">Connections</Link> page
            to see model health, failures, approvals and deployments here.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <section aria-label="Command center" className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <Section title="Model health" description="Latest score per server, lowest first." icon={<HeartPulse className="size-4" />}
          href="/health" count={d.health.filter((h) => h.score < 75).length} tour="dashboard-health">
          {!d.health.length ? <Empty>No health scans yet.</Empty> : (
            <ul className="space-y-1.5">
              {d.health.map((h) => (
                <li key={h.connection_id} className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 truncate">
                    <EnvironmentBadge environment={h.environment} />
                    {h.connection_name}
                  </span>
                  <span className={cn("font-semibold tabular-nums", h.score < 60 && "text-destructive")}>
                    {h.score} · {h.grade}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {d.risks.length ? (
            <div className="mt-3 border-t pt-2">
              <p className="mb-1 text-xs font-medium text-muted-foreground">Biggest model risks</p>
              <ul className="space-y-0.5 text-xs">
                {d.risks.slice(0, 4).map((r) => (
                  <li key={r.category}>
                    {r.label}: {r.count} (−{r.points} pts)
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </Section>

        <Section title="Active incidents" description="Open and in progress." icon={<Siren className="size-4" />}
          href="/team" count={d.incidents.length} urgent tour="dashboard-incidents">
          {!d.incidents.length ? <Empty>No open incidents.</Empty> : (
            <ul className="space-y-1.5">
              {d.incidents.map((i) => (
                <li key={i.id}>
                  <Link href={`/team/${i.id}`} className="hover:underline">
                    <span className="font-medium">{i.reference}</span> {i.title}
                  </Link>
                  {i.severity ? <Badge variant="outline" className="ml-1.5">{i.severity}</Badge> : null}
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Open alerts" description="Raised by monitoring rules." icon={<BellRing className="size-4" />}
          href="/alerts" count={d.alerts.open} urgent={d.alerts.critical > 0} tour="dashboard-alerts">
          {!d.alerts.open ? <Empty>No open alerts.</Empty> : (
            <ul className="space-y-1.5">
              {d.alerts.latest.map((a) => (
                <li key={a.id} className="truncate">
                  <Badge variant={a.severity === "critical" ? "destructive" : "outline"} className="mr-1.5">{a.severity}</Badge>
                  {a.title}
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Failed processes" description="Last 7 days, from TM1's message log." icon={<TriangleAlert className="size-4" />}
          href="/health" count={d.failed_processes.length} urgent tour="dashboard-failures">
          {!d.failed_processes.length ? <Empty>No failures recorded.</Empty> : (
            <ul className="space-y-1.5">
              {d.failed_processes.map((f) => (
                <li key={`${f.connection_id}-${f.process}`} className="flex justify-between gap-2">
                  <span className="truncate">{f.process} <span className="text-muted-foreground">· {f.connection_name}</span></span>
                  <span className="shrink-0 text-xs text-muted-foreground">{f.failed_runs_7_days}× · {when(f.last_failed_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Performance regressions" description="Runs far slower than usual." icon={<Timer className="size-4" />}
          href="/health" count={d.regressions.length} tour="dashboard-regressions">
          {!d.regressions.length ? <Empty>No regressions.</Empty> : (
            <ul className="space-y-1.5 text-xs">
              {d.regressions.map((r) => (
                <li key={`${r.connection_id}-${r.process}`}>{r.summary}</li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Waiting for approval" description="Valid drafts nobody has applied yet." icon={<Rocket className="size-4" />}
          href="/deployments" count={d.pending_approvals.length} tour="dashboard-approvals">
          {!d.pending_approvals.length ? <Empty>Nothing waiting.</Empty> : (
            <ul className="space-y-1.5">
              {d.pending_approvals.map((c) => (
                <li key={c.id} className="flex items-center gap-1.5 truncate">
                  <EnvironmentBadge environment={c.environment} />
                  <Link href={changeHref(c.connection_id, c.id)} className="truncate hover:underline">
                    {c.change_type.replaceAll("_", " ")} · {c.target_name}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2" data-tour="dashboard-deployments">
          <CardHeader>
            <CardTitle className="text-base">Recent deployments and model changes</CardTitle>
            <CardDescription>The last 14 days on the servers you can use.</CardDescription>
          </CardHeader>
          <CardContent className="text-sm">
            {!d.deployments.length && !d.model_changes.length ? <Empty>Nothing in the last 14 days.</Empty> : (
              <ul className="space-y-1.5">
                {d.deployments.map((c) => (
                  <li key={c.id} className="flex flex-wrap items-center gap-1.5">
                    <EnvironmentBadge environment={c.environment} />
                    <Link href={changeHref(c.connection_id, c.id)} className="hover:underline">
                      {c.change_type.replaceAll("_", " ")} · {c.target_name}
                    </Link>
                    <Badge variant={c.status === "failed" ? "destructive" : "outline"}>{c.status.replaceAll("_", " ")}</Badge>
                    <span className="text-xs text-muted-foreground">
                      {when(c.rolled_back_at ?? c.executed_at ?? c.created_at)}{c.by ? ` · ${c.by}` : ""}
                    </span>
                  </li>
                ))}
                {d.model_changes.map((m) => (
                  <li key={`${m.connection_id}-${m.at}`} className="flex flex-wrap items-center gap-1.5">
                    <EnvironmentBadge environment={m.environment} />
                    <span>
                      Model changed on {m.connection_name}:{" "}
                      {Object.entries(m.counts).map(([k, n]) => `${n} ${k.replaceAll("_", " ")}`).join(", ")}
                    </span>
                    <span className="text-xs text-muted-foreground">{when(m.at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        <Card data-tour="dashboard-ai-usage">
          <CardHeader>
            <CardTitle className="text-base">
              <Link href="/monitoring" className="hover:underline">AI usage and cost</Link>
            </CardTitle>
            <CardDescription>Your organization, last {d.ai.days} days.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            <p><span className="font-semibold tabular-nums">{d.ai.requests.toLocaleString()}</span> answers</p>
            <p><span className="font-semibold tabular-nums">${d.ai.cost_usd.toFixed(2)}</span> estimated cost</p>
            <p><span className="font-semibold tabular-nums">{(d.ai.avg_latency_ms / 1000).toFixed(1)} s</span> average answer time</p>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
