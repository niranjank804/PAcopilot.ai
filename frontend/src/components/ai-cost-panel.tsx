"use client";

import { useQuery } from "@tanstack/react-query";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiRequest } from "@/lib/api-client";

interface Group {
  name: string;
  requests: number;
  cost_usd: number;
  cost_per_request_usd: number;
}

interface CostReport {
  days: number;
  requests: number;
  total_cost_usd: number;
  cost_per_request_usd: number;
  tool_calls: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  fallback_rate: number;
  by_agent: Group[];
  by_tier: Group[];
  by_user: Group[];
  cache_savings_usd: number;
  auto_routing: { requests: number; estimated_savings_usd: number; assumption: string };
  notes: string[];
}

const usd = (value: number) =>
  value < 1 ? `$${value.toFixed(4)}` : `$${value.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;

function GroupList({ title, groups }: { title: string; groups: Group[] }) {
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-muted-foreground">{title}</p>
      {groups.length ? (
        <ul className="space-y-0.5 text-sm">
          {groups.slice(0, 8).map((g) => (
            <li key={g.name} className="flex justify-between gap-2">
              <span className="truncate">{g.name}</span>
              <span className="shrink-0 tabular-nums text-muted-foreground">
                {usd(g.cost_usd)} · {g.requests} · {usd(g.cost_per_request_usd)}/req
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">None.</p>
      )}
    </div>
  );
}

/**
 * Where AI spend goes — by agent, tier and person — and what caching and
 * AUTO routing saved. The AUTO figure is an estimate and is labelled as one.
 */
export function AICostPanel() {
  const report = useQuery({
    queryKey: ["monitoring-ai-costs"],
    queryFn: () => apiRequest<CostReport>("/monitoring/ai-costs?days=30"),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>AI Cost</CardTitle>
        <CardDescription>Last 30 days, from the usage ledger.</CardDescription>
      </CardHeader>
      <CardContent>
        {report.isPending ? (
          <Skeleton className="h-32 w-full" />
        ) : report.isError ? (
          <p className="text-sm text-destructive">Could not load AI cost.</p>
        ) : (
          <div className="space-y-5">
            <dl className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
              <div>
                <dt className="text-xs text-muted-foreground">Spend</dt>
                <dd className="text-lg font-semibold tabular-nums">{usd(report.data.total_cost_usd)}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Per request</dt>
                <dd className="text-lg font-semibold tabular-nums">{usd(report.data.cost_per_request_usd)}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Response time (avg / p95)</dt>
                <dd className="text-lg font-semibold tabular-nums">
                  {(report.data.avg_latency_ms / 1000).toFixed(1)} s / {(report.data.p95_latency_ms / 1000).toFixed(1)} s
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Fallback rate</dt>
                <dd className="text-lg font-semibold tabular-nums">
                  {(report.data.fallback_rate * 100).toFixed(1)}%
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Saved by caching</dt>
                <dd className="text-lg font-semibold tabular-nums">{usd(report.data.cache_savings_usd)}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Saved by AUTO (estimate)</dt>
                <dd className="text-lg font-semibold tabular-nums" title={report.data.auto_routing.assumption}>
                  {usd(report.data.auto_routing.estimated_savings_usd)}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Requests / tool calls</dt>
                <dd className="text-lg font-semibold tabular-nums">
                  {report.data.requests} / {report.data.tool_calls}
                </dd>
              </div>
            </dl>
            <div className="grid gap-6 md:grid-cols-3">
              <GroupList title="By agent (cost · requests · per request)" groups={report.data.by_agent} />
              <GroupList title="By tier" groups={report.data.by_tier} />
              <GroupList title="By person" groups={report.data.by_user} />
            </div>
            <ul className="space-y-0.5 text-xs text-muted-foreground">
              <li>{report.data.auto_routing.assumption}</li>
              {report.data.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
