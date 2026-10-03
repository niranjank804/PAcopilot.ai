"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { HeartPulse, Loader2, RefreshCw } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, apiRequest } from "@/lib/api-client";
import { fetchUsableConnections, USABLE_CONNECTIONS_KEY } from "@/lib/connections";
import type { TM1Connection } from "@/lib/types";

interface Deduction {
  category: string;
  label: string;
  count: number;
  points: number;
  points_each: number;
  cap: number;
  evidence: string[];
}

interface Scan {
  scanned_at: string;
  score: number;
  grade: string;
  trigger: string;
  deductions: Deduction[];
  totals: { notes?: string[]; cubes_analysed?: number; processes_analysed?: number; runs_known?: number };
}

interface Performance {
  rule: string;
  runs_known: number;
  regressions: { process: string; summary: string; increase_percent: number }[];
  slowest: { process: string; median_seconds: number; runs: number }[];
  failures_7_days: { process: string; failed_runs_7_days: number; last_failed_at: string; outcome: string }[];
  not_covered: string[];
}

interface HealthResponse {
  latest: Scan | null;
  trend: { scanned_at: string; score: number; grade: string; trigger: string }[];
  performance: Performance;
}

const GRADE_VARIANT: Record<string, "success" | "secondary" | "warning" | "destructive"> = {
  A: "success",
  B: "secondary",
  C: "warning",
  D: "destructive",
  F: "destructive",
};

function seconds(value: number): string {
  if (value < 90) return `${Math.round(value)} s`;
  const minutes = Math.floor(value / 60);
  return minutes < 90 ? `${minutes} min ${Math.round(value % 60)} s` : `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

export default function HealthPage() {
  const queryClient = useQueryClient();
  const [chosen, setChosen] = useState<string | null>(null);

  const connections = useQuery({
    queryKey: USABLE_CONNECTIONS_KEY,
    queryFn: fetchUsableConnections,
  });
  const connectionId = chosen ?? connections.data?.[0]?.id ?? null;

  const health = useQuery({
    queryKey: ["tm1-health", connectionId],
    queryFn: () => apiRequest<HealthResponse>(`/tm1/connections/${connectionId}/health`),
    enabled: Boolean(connectionId),
  });

  const scan = useMutation({
    mutationFn: () =>
      apiRequest(`/tm1/connections/${connectionId}/health/scan`, { method: "POST", timeoutMs: 290_000 }),
    onSuccess: () => {
      toast.success("Scan finished.");
      queryClient.invalidateQueries({ queryKey: ["tm1-health", connectionId] });
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : "The scan failed."),
  });

  const latest = health.data?.latest;
  const perf = health.data?.performance;
  const charged = latest?.deductions.filter((d) => d.count > 0) ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="page-title">Model Health</h1>
          <p className="text-sm text-muted-foreground">
            A score with the evidence behind every point, and how long processes take — so
            &ldquo;it feels slow&rdquo; becomes &ldquo;it took 7 minutes instead of 42 seconds&rdquo;.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {connectionId ? (
            <Select value={connectionId} onValueChange={(value) => value && setChosen(value)}>
              <SelectTrigger className="w-56" aria-label="Connection">
                <SelectValue>
                  {(value: string) => connections.data?.find((c) => c.id === value)?.name ?? "Connection"}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {connections.data?.map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : null}
          <Button onClick={() => scan.mutate()} disabled={!connectionId || scan.isPending}>
            {scan.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
            {scan.isPending ? "Scanning…" : "Scan now"}
          </Button>
        </div>
      </div>

      {!connectionId ? (
        <p className="text-sm text-muted-foreground">Add a TM1 connection to score its health.</p>
      ) : health.isPending ? (
        <Skeleton className="h-48 w-full" />
      ) : health.isError ? (
        <p className="text-sm text-destructive">Could not load model health.</p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <HeartPulse className="size-4" aria-hidden />
                Health score
              </CardTitle>
              <CardDescription>
                {latest
                  ? `Scanned ${new Date(latest.scanned_at).toLocaleString()} (${latest.trigger === "schedule" ? "daily" : "manual"}). Rescanned daily once scanned.`
                  : "Not scanned yet. Scan now to score this model."}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {latest ? (
                <div className="flex items-baseline gap-3">
                  <span className="text-5xl font-semibold tabular-nums">{latest.score}</span>
                  <span className="text-sm text-muted-foreground">/ 100</span>
                  <Badge variant={GRADE_VARIANT[latest.grade] ?? "secondary"}>Grade {latest.grade}</Badge>
                </div>
              ) : null}
              {health.data.trend.length > 1 ? (
                <div>
                  <p className="mb-1 text-xs font-medium text-muted-foreground">Recent scores</p>
                  <ul className="space-y-0.5 text-xs">
                    {health.data.trend.map((t) => (
                      <li key={t.scanned_at} className="flex justify-between gap-2">
                        <span className="text-muted-foreground">{new Date(t.scanned_at).toLocaleDateString()}</span>
                        <span className="tabular-nums">
                          {t.score} ({t.grade})
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {latest?.totals.notes?.map((note) => (
                <p key={note} className="text-xs text-warning">
                  {note}
                </p>
              ))}
            </CardContent>
          </Card>

          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle className="text-base">Where the points went</CardTitle>
              <CardDescription>
                100, minus fixed points per finding, capped per category. Each line lists what cost it.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {!latest ? (
                <p className="text-sm text-muted-foreground">Scan to see the breakdown.</p>
              ) : !charged.length ? (
                <p className="text-sm text-muted-foreground">Nothing found in the objects analysed.</p>
              ) : (
                <ul className="divide-y text-sm">
                  {charged.map((d) => (
                    <li key={d.category} className="space-y-1 py-2">
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <span className="font-medium">
                          {d.label}: {d.count}
                        </span>
                        <span className="text-xs text-muted-foreground tabular-nums">
                          −{d.points} ({d.points_each} each, at most {d.cap})
                        </span>
                      </div>
                      {d.evidence.length ? (
                        <ul className="list-disc pl-4 text-xs text-muted-foreground">
                          {d.evidence.map((e) => (
                            <li key={e} className="break-words">
                              {e}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          {perf ? (
            <Card className="lg:col-span-3">
              <CardHeader>
                <CardTitle className="text-base">Performance</CardTitle>
                <CardDescription>
                  From {perf.runs_known} run{perf.runs_known === 1 ? "" : "s"} collected from TM1&apos;s message log
                  and PA-Copilot&apos;s own runs. {perf.rule}
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-6 md:grid-cols-3">
                <div>
                  <p className="mb-1 text-xs font-medium text-muted-foreground">Regressions</p>
                  {perf.regressions.length ? (
                    <ul className="space-y-2 text-sm">
                      {perf.regressions.map((r) => (
                        <li key={r.process}>{r.summary}</li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-muted-foreground">None detected.</p>
                  )}
                </div>
                <div>
                  <p className="mb-1 text-xs font-medium text-muted-foreground">Slowest (median)</p>
                  {perf.slowest.length ? (
                    <ul className="space-y-0.5 text-sm">
                      {perf.slowest.map((s) => (
                        <li key={s.process} className="flex justify-between gap-2">
                          <span className="truncate">{s.process}</span>
                          <span className="shrink-0 tabular-nums text-muted-foreground">
                            {seconds(s.median_seconds)} · {s.runs} runs
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-muted-foreground">No timed runs collected yet.</p>
                  )}
                </div>
                <div>
                  <p className="mb-1 text-xs font-medium text-muted-foreground">Failed in the last 7 days</p>
                  {perf.failures_7_days.length ? (
                    <ul className="space-y-0.5 text-sm">
                      {perf.failures_7_days.map((f) => (
                        <li key={f.process}>
                          {f.process}: {f.failed_runs_7_days} ({f.outcome.replaceAll("_", " ")}, last{" "}
                          {new Date(f.last_failed_at).toLocaleString()})
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-muted-foreground">None.</p>
                  )}
                </div>
                <p className="text-xs text-muted-foreground md:col-span-3">
                  Not covered: {perf.not_covered.join("; ")}.
                </p>
              </CardContent>
            </Card>
          ) : null}
        </div>
      )}
    </div>
  );
}
