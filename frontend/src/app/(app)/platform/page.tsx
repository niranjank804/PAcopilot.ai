"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, History, LogOut, Pause, Play, ShieldOff, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { download } from "@/components/visualize/chart-builder";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, apiRequest } from "@/lib/api-client";
import {
  ago,
  auditCsv,
  device,
  type AuditRow,
  type PlatformConnection,
  type PlatformOverview,
  type PlatformUser,
  type SignIn,
  type UserActivity,
} from "@/lib/platform";

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong.";
}

function when(value: string | null) {
  return value ? <span title={new Date(value).toLocaleString()}>{ago(value)}</span> : "never";
}

/** A restricting action, confirmed with an optional reason that goes into
 * the audit log. */
interface PendingAction {
  title: string;
  description: string;
  confirm: string;
  path: string;
  destructive: boolean;
}

export default function PlatformPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [reason, setReason] = useState("");
  const [activityFor, setActivityFor] = useState<PlatformUser | null>(null);

  const overview = useQuery({
    queryKey: ["platform-overview"],
    queryFn: () => apiRequest<PlatformOverview>("/admin/platform/overview"),
    retry: false,
  });
  const users = useQuery({
    queryKey: ["platform-users"],
    queryFn: () => apiRequest<PlatformUser[]>("/admin/platform/users"),
    retry: false,
  });
  const connections = useQuery({
    queryKey: ["platform-connections"],
    queryFn: () => apiRequest<PlatformConnection[]>("/admin/platform/connections"),
    retry: false,
  });
  const signIns = useQuery({
    queryKey: ["platform-sign-ins"],
    queryFn: () => apiRequest<SignIn[]>("/admin/platform/sign-ins?limit=300"),
    retry: false,
  });
  const audit = useQuery({
    queryKey: ["platform-audit"],
    queryFn: () => apiRequest<AuditRow[]>("/admin/platform/audit?limit=500"),
    retry: false,
  });

  const act = useMutation({
    mutationFn: (action: PendingAction) =>
      apiRequest(action.path, { method: "POST", body: { reason } }),
    onSuccess: () => {
      toast.success("Done. It is recorded in the audit log.");
      setPending(null);
      setReason("");
      for (const key of ["platform-overview", "platform-users", "platform-connections", "platform-audit"]) {
        queryClient.invalidateQueries({ queryKey: [key] });
      }
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const needle = search.trim().toLowerCase();
  const shownUsers = useMemo(
    () =>
      (users.data ?? []).filter((u) =>
        !needle || [u.name, u.email, u.username, u.organization, u.last_ip ?? ""].some((v) => v.toLowerCase().includes(needle)),
      ),
    [users.data, needle],
  );
  const shownConnections = useMemo(
    () =>
      (connections.data ?? []).filter((c) =>
        !needle ||
        [c.name, c.address, c.tm1_user, c.organization, c.owner?.email ?? "", c.database ?? ""].some((v) =>
          v.toLowerCase().includes(needle),
        ),
      ),
    [connections.data, needle],
  );

  if (overview.error instanceof ApiError && overview.error.status === 403) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Platform</CardTitle>
          <CardDescription>Only the platform&apos;s Super Admin can open this page.</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const o = overview.data;
  const tiles: [string, string | number | undefined, string?][] = [
    ["Workspaces", o?.organizations],
    ["People", o?.users, o ? `${o.pending_signups} waiting for approval` : undefined],
    ["Active in 24 h", o?.active_users_24h],
    ["Sign-ins in 24 h", o?.sign_ins_24h, o ? `${o.failed_sign_ins_24h} failed` : undefined],
    ["TM1 connections", o?.connections, o ? `${o.suspended_connections} suspended` : undefined],
    ["AI requests in 24 h", o?.ai_requests_24h, o ? `$${o.ai_cost_24h.toFixed(2)}` : undefined],
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="page-title">Platform</h1>
        <p className="text-sm text-muted-foreground">
          Everyone on PA-Copilot across every workspace: who signs in and from where, which TM1
          servers they connect with which TM1 user, and what they do there. Passwords and API keys
          are never shown. Every restriction you apply is recorded in the audit log.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6" data-tour="platform-overview">
        {tiles.map(([label, value, sub]) => (
          <Card key={label}>
            <CardContent className="p-4">
              <p className="text-xs text-muted-foreground">{label}</p>
              <p className="text-2xl font-semibold tabular-nums">
                {value ?? <Skeleton className="mt-1 h-7 w-12" />}
              </p>
              {sub ? <p className="text-xs text-muted-foreground">{sub}</p> : null}
            </CardContent>
          </Card>
        ))}
      </div>

      <Input
        placeholder="Search people, emails, workspaces, servers, TM1 users or addresses"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        className="max-w-xl"
        data-tour="platform-search"
      />

      <Tabs defaultValue="people">
        <TabsList data-tour="platform-tabs">
          <TabsTrigger value="people">People</TabsTrigger>
          <TabsTrigger value="connections">TM1 connections</TabsTrigger>
          <TabsTrigger value="sign-ins">Sign-ins</TabsTrigger>
          <TabsTrigger value="audit">Audit log</TabsTrigger>
        </TabsList>

        <TabsContent value="people">
          <Card data-tour="platform-people">
            <CardContent className="overflow-x-auto p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Person</TableHead>
                    <TableHead>Workspace</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Last sign-in</TableHead>
                    <TableHead>Last active</TableHead>
                    <TableHead>From</TableHead>
                    <TableHead className="text-right">Servers used (30 d)</TableHead>
                    <TableHead className="text-right">AI (30 d)</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {users.isLoading ? (
                    <TableRow><TableCell colSpan={9}><Skeleton className="h-6 w-full" /></TableCell></TableRow>
                  ) : shownUsers.map((u) => (
                    <TableRow key={u.id}>
                      <TableCell>
                        <div className="font-medium">{u.name}</div>
                        <div className="text-xs text-muted-foreground">{u.email}</div>
                      </TableCell>
                      <TableCell>
                        <div>{u.organization}</div>
                        <div className="text-xs text-muted-foreground">{u.roles.join(", ") || "no role"}</div>
                      </TableCell>
                      <TableCell>
                        {!u.is_active ? (
                          <Badge variant="destructive">deactivated</Badge>
                        ) : u.registration_status !== "approved" ? (
                          <Badge variant="warning">{u.registration_status}</Badge>
                        ) : (
                          <Badge variant="success">active</Badge>
                        )}
                      </TableCell>
                      <TableCell>{when(u.last_login_at)}</TableCell>
                      <TableCell>{when(u.last_seen_at)}</TableCell>
                      <TableCell className="font-mono text-xs">{u.last_ip ?? "—"}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {u.connections_used_30d}
                        <span className="text-muted-foreground"> · owns {u.connections_owned}</span>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {u.ai_requests_30d}
                        <span className="text-muted-foreground"> · ${u.ai_cost_30d.toFixed(2)}</span>
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end gap-1" data-tour="platform-person-actions">
                          <Button size="sm" variant="ghost" onClick={() => setActivityFor(u)} title="What they did">
                            <History className="h-4 w-4" />
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            title="End all their sessions"
                            onClick={() =>
                              setPending({
                                title: `Sign ${u.name} out everywhere?`,
                                description: "Every session ends now. They can sign in again.",
                                confirm: "Sign out",
                                path: `/admin/platform/users/${u.id}/sign-out`,
                                destructive: false,
                              })
                            }
                          >
                            <LogOut className="h-4 w-4" />
                          </Button>
                          {u.is_active ? (
                            <Button
                              size="sm"
                              variant="ghost"
                              title="Deactivate"
                              onClick={() =>
                                setPending({
                                  title: `Deactivate ${u.name}?`,
                                  description:
                                    "They are signed out at once and cannot sign in or use any server until reactivated. Their data is kept.",
                                  confirm: "Deactivate",
                                  path: `/admin/platform/users/${u.id}/deactivate`,
                                  destructive: true,
                                })
                              }
                            >
                              <ShieldOff className="h-4 w-4 text-destructive" />
                            </Button>
                          ) : (
                            <Button
                              size="sm"
                              variant="ghost"
                              title="Reactivate"
                              onClick={() =>
                                setPending({
                                  title: `Reactivate ${u.name}?`,
                                  description: "They can sign in again.",
                                  confirm: "Reactivate",
                                  path: `/admin/platform/users/${u.id}/activate`,
                                  destructive: false,
                                })
                              }
                            >
                              <ShieldCheck className="h-4 w-4" />
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="connections">
          <Card data-tour="platform-connections">
            <CardContent className="overflow-x-auto p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Connection</TableHead>
                    <TableHead>Workspace · owner</TableHead>
                    <TableHead>Server</TableHead>
                    <TableHead>TM1 user</TableHead>
                    <TableHead>Env</TableHead>
                    <TableHead>Last used</TableHead>
                    <TableHead>Used by (30 d)</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {connections.isLoading ? (
                    <TableRow><TableCell colSpan={8}><Skeleton className="h-6 w-full" /></TableCell></TableRow>
                  ) : shownConnections.map((c) => (
                    <TableRow key={c.id}>
                      <TableCell>
                        <div className="font-medium">{c.name}</div>
                        <div className="flex flex-wrap gap-1 pt-1">
                          {c.suspended_at ? <Badge variant="destructive">suspended</Badge> : null}
                          <Badge variant="secondary">{c.visibility === "organization" ? "shared" : "private"}</Badge>
                          {c.gateway ? <Badge variant="secondary">via {c.gateway}</Badge> : null}
                        </div>
                        {c.suspended_reason ? (
                          <div className="pt-1 text-xs text-muted-foreground">{c.suspended_reason}</div>
                        ) : null}
                      </TableCell>
                      <TableCell>
                        <div>{c.organization}</div>
                        <div className="text-xs text-muted-foreground">{c.owner?.email ?? "—"}</div>
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {c.address}:{c.port}{c.ssl ? " (SSL)" : ""}
                        {c.database ? <div>db {c.database}{c.tenant ? ` · tenant ${c.tenant}` : ""}</div> : null}
                        <div className="font-sans text-muted-foreground">{c.authentication_type}</div>
                      </TableCell>
                      <TableCell className="font-mono text-xs">{c.tm1_user}</TableCell>
                      <TableCell><Badge variant={c.environment === "prod" ? "warning" : "secondary"}>{c.environment.toUpperCase()}</Badge></TableCell>
                      <TableCell>{when(c.last_used_at)}</TableCell>
                      <TableCell className="text-xs">
                        {c.used_by_30d.length ? c.used_by_30d.map((p) => p.email).join(", ") : "—"}
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end" data-tour="platform-connection-actions">
                          {c.suspended_at ? (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() =>
                                setPending({
                                  title: `Resume ${c.name}?`,
                                  description: "Its workspace can use it again.",
                                  confirm: "Resume",
                                  path: `/admin/platform/connections/${c.id}/resume`,
                                  destructive: false,
                                })
                              }
                            >
                              <Play className="mr-1.5 h-3.5 w-3.5" /> Resume
                            </Button>
                          ) : (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() =>
                                setPending({
                                  title: `Suspend ${c.name}?`,
                                  description:
                                    "Nothing can use this connection's credentials — chat, alerts, deployments or scheduled jobs — until you resume it. Its owner sees that it is suspended and your reason.",
                                  confirm: "Suspend",
                                  path: `/admin/platform/connections/${c.id}/suspend`,
                                  destructive: true,
                                })
                              }
                            >
                              <Pause className="mr-1.5 h-3.5 w-3.5" /> Suspend
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="sign-ins">
          <Card data-tour="platform-sign-ins">
            <CardContent className="overflow-x-auto p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>When</TableHead>
                    <TableHead>Result</TableHead>
                    <TableHead>Who</TableHead>
                    <TableHead>Method</TableHead>
                    <TableHead>Address</TableHead>
                    <TableHead>Device</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(signIns.data ?? [])
                    .filter((s) =>
                      !needle || [s.identifier ?? "", s.user?.email ?? "", s.ip_address ?? "", s.organization ?? ""]
                        .some((v) => v.toLowerCase().includes(needle)),
                    )
                    .map((s) => (
                      <TableRow key={s.id}>
                        <TableCell>{when(s.at)}</TableCell>
                        <TableCell>
                          {s.success ? (
                            <Badge variant="success">signed in</Badge>
                          ) : (
                            <Badge variant="destructive" title={s.reason ?? undefined}>failed</Badge>
                          )}
                          {!s.success && s.reason ? (
                            <div className="pt-1 text-xs text-muted-foreground">{s.reason}</div>
                          ) : null}
                        </TableCell>
                        <TableCell>
                          <div>{s.user?.name ?? s.identifier ?? "unknown"}</div>
                          <div className="text-xs text-muted-foreground">
                            {s.user ? `${s.user.email} · ${s.organization ?? ""}` : "no such account"}
                          </div>
                        </TableCell>
                        <TableCell>{s.method}</TableCell>
                        <TableCell className="font-mono text-xs">{s.ip_address ?? "—"}</TableCell>
                        <TableCell className="text-xs">{device(s.user_agent)}</TableCell>
                      </TableRow>
                    ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="audit">
          <Card data-tour="platform-audit">
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <CardDescription>
                Every recorded action across all workspaces, newest first (last 500).
              </CardDescription>
              <Button
                size="sm"
                variant="outline"
                disabled={!audit.data?.length}
                onClick={() => audit.data && download("pa-copilot-audit-log.csv", auditCsv(audit.data), "text/csv")}
              >
                <Download className="mr-1.5 h-3.5 w-3.5" /> Export CSV
              </Button>
            </CardHeader>
            <CardContent className="overflow-x-auto p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>When</TableHead>
                    <TableHead>Who</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead>On</TableHead>
                    <TableHead>Details</TableHead>
                    <TableHead>Address</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(audit.data ?? [])
                    .filter((a) =>
                      !needle || [a.action, a.user?.email ?? "", a.organization ?? "", a.connection ?? "", a.ip_address ?? ""]
                        .some((v) => v.toLowerCase().includes(needle)),
                    )
                    .map((a) => (
                      <TableRow key={a.id}>
                        <TableCell>{when(a.at)}</TableCell>
                        <TableCell>
                          <div>{a.user?.name ?? "system"}</div>
                          <div className="text-xs text-muted-foreground">{a.organization ?? ""}</div>
                        </TableCell>
                        <TableCell className="font-mono text-xs">{a.action}</TableCell>
                        <TableCell>{a.connection ?? a.entity}</TableCell>
                        <TableCell className="max-w-md truncate text-xs text-muted-foreground" title={JSON.stringify(a.details)}>
                          {Object.entries(a.details).map(([k, v]) => `${k}: ${v}`).join(" · ") || "—"}
                        </TableCell>
                        <TableCell className="font-mono text-xs">{a.ip_address ?? "—"}</TableCell>
                      </TableRow>
                    ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <Dialog open={pending !== null} onOpenChange={(open) => { if (!open) { setPending(null); setReason(""); } }}>
        <DialogContent>
          <DialogTitle>{pending?.title}</DialogTitle>
          <p className="text-sm text-muted-foreground">{pending?.description}</p>
          <Textarea
            placeholder="Reason (kept in the audit log)"
            value={reason}
            maxLength={500}
            onChange={(event) => setReason(event.target.value)}
          />
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setPending(null)}>Cancel</Button>
            <Button
              variant={pending?.destructive ? "destructive" : "default"}
              disabled={act.isPending}
              onClick={() => pending && act.mutate(pending)}
            >
              {pending?.confirm}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <ActivityDialog person={activityFor} onClose={() => setActivityFor(null)} />
    </div>
  );
}

function ActivityDialog({ person, onClose }: { person: PlatformUser | null; onClose: () => void }) {
  const activity = useQuery({
    queryKey: ["platform-activity", person?.id],
    queryFn: () => apiRequest<UserActivity>(`/admin/platform/users/${person?.id}/activity?days=30`),
    enabled: person !== null,
    retry: false,
  });

  return (
    <Dialog open={person !== null} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="max-h-[85vh] w-[min(64rem,calc(100vw-2rem))] max-w-none overflow-y-auto sm:max-w-none">
        <DialogTitle>
          {person?.name} · {person?.email}
        </DialogTitle>
        <p className="text-sm text-muted-foreground">
          The last 30 days: what they did through the app, every TM1 call the assistant made for
          them with the server and objects it touched, and their sign-ins.
        </p>
        {activity.isLoading ? <Skeleton className="h-40 w-full" /> : null}
        {activity.error ? <p className="text-sm text-destructive">{errorMessage(activity.error)}</p> : null}
        {activity.data ? (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>What</TableHead>
                  <TableHead>Server</TableHead>
                  <TableHead>Details</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {activity.data.events.length === 0 ? (
                  <TableRow><TableCell colSpan={4} className="text-muted-foreground">Nothing recorded.</TableCell></TableRow>
                ) : activity.data.events.map((e, i) => (
                  <TableRow key={`${e.at}-${i}`}>
                    <TableCell>{when(e.at)}</TableCell>
                    <TableCell>
                      <span className="font-mono text-xs">{e.action}</span>
                      <div className="text-xs text-muted-foreground">
                        {e.kind === "tool" ? `assistant (${e.entity})` : e.entity}
                        {e.status && e.status !== "success" ? ` · ${e.status}` : ""}
                      </div>
                    </TableCell>
                    <TableCell>{e.connection?.name ?? "—"}</TableCell>
                    <TableCell className="max-w-md truncate text-xs text-muted-foreground" title={JSON.stringify(e.details)}>
                      {Object.entries(e.details).map(([k, v]) => `${k}: ${v}`).join(" · ") || "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <h3 className="pt-2 text-sm font-semibold">Sign-ins</h3>
            <Table>
              <TableBody>
                {activity.data.sign_ins.length === 0 ? (
                  <TableRow><TableCell className="text-muted-foreground">None recorded yet.</TableCell></TableRow>
                ) : activity.data.sign_ins.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell>{when(s.at)}</TableCell>
                    <TableCell>{s.success ? "signed in" : `failed: ${s.reason ?? ""}`}</TableCell>
                    <TableCell>{s.method}</TableCell>
                    <TableCell className="font-mono text-xs">{s.ip_address ?? "—"}</TableCell>
                    <TableCell className="text-xs">{device(s.user_agent)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
