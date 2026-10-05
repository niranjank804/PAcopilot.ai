"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCheck, Pause, Play, Plus, RefreshCw, Sparkles, Trash2, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { EnvironmentBadge } from "@/components/environment-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, apiRequest } from "@/lib/api-client";
import { USABLE_CONNECTIONS_KEY, fetchUsableConnections } from "@/lib/connections";
import {
  KIND_FIELDS,
  OPEN_ALERTS_KEY,
  type MonitorAlert,
  type MonitorKind,
  type MonitorRule,
  type MonitoringSetup,
} from "@/lib/monitoring";
import { when } from "@/lib/team";
import { cn } from "@/lib/utils";

function message(error: unknown) {
  return error instanceof ApiError ? error.message : "Something went wrong.";
}

const SEVERITY_VARIANT = { critical: "destructive", warning: "warning", info: "outline" } as const;
const ALERT_TABS = [
  { value: "open", label: "Open" },
  { value: "acknowledged", label: "Acknowledged" },
  { value: "resolved", label: "Resolved" },
] as const;

/**
 * What the monitoring rules found, and the rules themselves. Rules only
 * read TM1; the assistant's suggestions wait here until someone turns
 * them on.
 */
export default function AlertsPage() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<(typeof ALERT_TABS)[number]["value"]>("open");
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState<{ connection: string; kind: MonitorKind; params: Record<string, string> }>({
    connection: "",
    kind: "process_failure",
    params: {},
  });

  const setup = useQuery({
    queryKey: ["monitoring", "setup"],
    queryFn: () => apiRequest<MonitoringSetup>("/monitoring/setup"),
  });
  const alerts = useQuery({
    queryKey: ["monitoring", "alerts", tab],
    queryFn: () => apiRequest<MonitorAlert[]>(`/monitoring/alerts?status=${tab}`),
  });
  const rules = useQuery({
    queryKey: ["monitoring", "rules"],
    queryFn: () => apiRequest<MonitorRule[]>("/monitoring/rules"),
  });
  const connections = useQuery({ queryKey: USABLE_CONNECTIONS_KEY, queryFn: fetchUsableConnections });
  const byId = new Map((connections.data ?? []).map((c) => [c.id, c]));

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["monitoring"] });
    queryClient.invalidateQueries({ queryKey: OPEN_ALERTS_KEY });
  };

  const alertAction = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "acknowledge" | "resolve" }) =>
      apiRequest(`/monitoring/alerts/${id}/${action}`, { method: "POST" }),
    onSuccess: refresh,
    onError: (error) => toast.error(message(error)),
  });

  const updateRule = useMutation({
    mutationFn: ({ id, status }: { id: string; status: "active" | "paused" }) =>
      apiRequest<MonitorRule>(`/monitoring/rules/${id}`, { method: "PATCH", body: { status } }),
    onSuccess: (rule) => {
      toast.success(rule.status === "active" ? "On — checked every 15 minutes from now." : "Paused.");
      refresh();
    },
    onError: (error) => toast.error(message(error)),
  });

  const deleteRule = useMutation({
    mutationFn: (id: string) => apiRequest(`/monitoring/rules/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Rule deleted.");
      refresh();
    },
    onError: (error) => toast.error(message(error)),
  });

  const checkNow = useMutation({
    mutationFn: (id: string) => apiRequest<MonitorAlert[]>(`/monitoring/rules/${id}/check`, { method: "POST" }),
    onSuccess: (raised) => {
      toast.success(raised.length ? `${raised.length} new alert(s).` : "Checked — nothing new.");
      refresh();
    },
    onError: (error) => toast.error(message(error)),
  });

  const create = useMutation({
    mutationFn: () => {
      const params: Record<string, string | number> = {};
      for (const field of KIND_FIELDS[draft.kind]) {
        const raw = (draft.params[field.key] ?? field.initial ?? "").trim();
        if (raw) params[field.key] = field.type === "number" ? Number(raw) : raw;
      }
      return apiRequest<MonitorRule>("/monitoring/rules", {
        method: "POST",
        body: { connection_id: draft.connection, kind: draft.kind, params },
      });
    },
    onSuccess: (rule) => {
      toast.success(`Watching: ${rule.name}. The first check sets the baseline.`);
      setCreating(false);
      setDraft({ connection: "", kind: "process_failure", params: {} });
      refresh();
    },
    onError: (error) => toast.error(message(error)),
  });

  const proposed = rules.data?.filter((r) => r.status === "proposed") ?? [];
  const watching = rules.data?.filter((r) => r.status !== "proposed") ?? [];
  const missingRequired = KIND_FIELDS[draft.kind].some(
    (f) => f.required && !(draft.params[f.key] ?? "").trim(),
  );

  const serverLabel = (connectionId: string) => {
    const c = byId.get(connectionId);
    return c ? (
      <span className="inline-flex items-center gap-1.5">
        <EnvironmentBadge environment={c.environment} />
        {c.name}
      </span>
    ) : null;
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="page-title">Alerts</h1>
          <p className="text-sm text-muted-foreground">
            Rules that watch your TM1 servers — failed and slow processes, dimension growth,
            security, model and deployment changes. They only read; nothing is ever changed.
          </p>
        </div>
        <Button onClick={() => setCreating(true)}>
          <Plus className="mr-2 h-4 w-4" />
          New rule
        </Button>
      </div>

      {setup.data && !setup.data.email_configured ? (
        <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
          Email is not set up on this deployment, so alerts appear here and on the bell only. An
          administrator can add SMTP settings to send them by email too.
        </p>
      ) : null}

      {proposed.length ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Suggested by the assistant</CardTitle>
            <CardDescription>Not checked until you turn them on.</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="divide-y">
              {proposed.map((r) => (
                <li key={r.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
                  <div className="min-w-0 space-y-1 text-sm">
                    <p className="flex items-center gap-1.5 font-medium">
                      <Sparkles className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
                      {r.name}
                    </p>
                    <p className="text-xs text-muted-foreground">{serverLabel(r.connection_id)}</p>
                    {r.rationale ? <p className="text-xs">You asked: {r.rationale}</p> : null}
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <Button size="sm" onClick={() => updateRule.mutate({ id: r.id, status: "active" })} disabled={updateRule.isPending}>
                      <Play className="mr-1 h-3.5 w-3.5" />
                      Turn on
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => deleteRule.mutate(r.id)} disabled={deleteRule.isPending}>
                      <X className="mr-1 h-3.5 w-3.5" />
                      Discard
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
          <CardTitle className="text-base">Alerts</CardTitle>
          <div className="flex gap-1" role="group" aria-label="Alert status">
            {ALERT_TABS.map((t) => (
              <Button
                key={t.value}
                size="sm"
                variant={tab === t.value ? "secondary" : "ghost"}
                aria-pressed={tab === t.value}
                onClick={() => setTab(t.value)}
              >
                {t.label}
              </Button>
            ))}
          </div>
        </CardHeader>
        <CardContent>
          {alerts.isPending ? (
            <Skeleton className="h-16 w-full" />
          ) : alerts.isError ? (
            <p className="text-sm text-destructive">{message(alerts.error)}</p>
          ) : !alerts.data.length ? (
            <p className="text-sm text-muted-foreground">
              {tab === "open" ? "No open alerts." : `No ${tab} alerts.`}
            </p>
          ) : (
            <ul className="divide-y">
              {alerts.data.map((a) => (
                <li key={a.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
                  <div className="min-w-0 space-y-1 text-sm">
                    <p className="flex flex-wrap items-center gap-2 font-medium">
                      <Badge variant={SEVERITY_VARIANT[a.severity]}>{a.severity}</Badge>
                      {a.title}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {serverLabel(a.connection_id)} · {when(a.fired_at)}
                      {a.emailed ? " · emailed" : ""}
                    </p>
                    {a.detail ? <p className="whitespace-pre-wrap text-xs">{a.detail}</p> : null}
                  </div>
                  {a.status !== "resolved" ? (
                    <div className="flex shrink-0 gap-2">
                      {a.status === "open" ? (
                        <Button size="sm" variant="outline" onClick={() => alertAction.mutate({ id: a.id, action: "acknowledge" })} disabled={alertAction.isPending}>
                          <Check className="mr-1 h-3.5 w-3.5" />
                          Acknowledge
                        </Button>
                      ) : null}
                      <Button size="sm" variant="outline" onClick={() => alertAction.mutate({ id: a.id, action: "resolve" })} disabled={alertAction.isPending}>
                        <CheckCheck className="mr-1 h-3.5 w-3.5" />
                        Resolve
                      </Button>
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Rules</CardTitle>
          <CardDescription>Checked every 15 minutes. The first check of a rule sets its baseline.</CardDescription>
        </CardHeader>
        <CardContent>
          {rules.isPending ? (
            <Skeleton className="h-16 w-full" />
          ) : !watching.length ? (
            <p className="text-sm text-muted-foreground">
              No rules yet. Add one, or ask the assistant: “Alert me if Workforce Planning takes
              more than twice its 30-day average.”
            </p>
          ) : (
            <ul className="divide-y">
              {watching.map((r) => (
                <li key={r.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
                  <div className={cn("min-w-0 space-y-1 text-sm", r.status === "paused" && "opacity-60")}>
                    <p className="font-medium">
                      {r.name}
                      {r.status === "paused" ? <span className="ml-2 text-xs font-normal">(paused)</span> : null}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {serverLabel(r.connection_id)} ·{" "}
                      {r.last_checked_at ? `last checked ${when(r.last_checked_at)}` : "not checked yet"}
                    </p>
                    {r.last_error ? (
                      <p className="text-xs text-destructive">
                        Last check failed{r.consecutive_errors > 1 ? ` (${r.consecutive_errors} in a row)` : ""}: {r.last_error}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <Button size="sm" variant="ghost" aria-label="Check now" title="Check now" disabled={checkNow.isPending || r.status !== "active"} onClick={() => checkNow.mutate(r.id)}>
                      <RefreshCw className={cn("h-3.5 w-3.5", checkNow.isPending && checkNow.variables === r.id && "animate-spin")} />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={r.status === "active" ? "Pause" : "Resume"}
                      title={r.status === "active" ? "Pause" : "Resume"}
                      disabled={updateRule.isPending}
                      onClick={() => updateRule.mutate({ id: r.id, status: r.status === "active" ? "paused" : "active" })}
                    >
                      {r.status === "active" ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                    </Button>
                    <Button size="sm" variant="ghost" aria-label="Delete rule" title="Delete" disabled={deleteRule.isPending} onClick={() => deleteRule.mutate(r.id)}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New monitoring rule</DialogTitle>
            <DialogDescription>
              It only reads the server. You are emailed when it fires
              {setup.data?.email_configured ? "" : " (once email is set up)"}.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="rule-server">Server</Label>
              <Select value={draft.connection} onValueChange={(value) => setDraft({ ...draft, connection: value ?? "" })}>
                <SelectTrigger id="rule-server" className="w-full">
                  <SelectValue placeholder="Choose a server">
                    {(value: string) => byId.get(value)?.name ?? "Choose a server"}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {(connections.data ?? []).map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      {c.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="rule-kind">Alert when</Label>
              <Select
                value={draft.kind}
                onValueChange={(value) => value && setDraft({ ...draft, kind: value as MonitorKind, params: {} })}
              >
                <SelectTrigger id="rule-kind" className="w-full">
                  <SelectValue>
                    {(value: MonitorKind) => setup.data?.kinds.find((k) => k.kind === value)?.label ?? value}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {(setup.data?.kinds ?? []).map((k) => (
                    <SelectItem key={k.kind} value={k.kind}>
                      {k.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {KIND_FIELDS[draft.kind].map((field) => (
              <div key={field.key} className="space-y-1">
                <Label htmlFor={`rule-${field.key}`}>{field.label}</Label>
                <Input
                  id={`rule-${field.key}`}
                  type={field.type}
                  placeholder={field.placeholder}
                  value={draft.params[field.key] ?? field.initial ?? ""}
                  onChange={(event) =>
                    setDraft({ ...draft, params: { ...draft.params, [field.key]: event.target.value } })
                  }
                />
              </div>
            ))}
            <Button onClick={() => create.mutate()} disabled={!draft.connection || missingRequired || create.isPending}>
              Start watching
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
