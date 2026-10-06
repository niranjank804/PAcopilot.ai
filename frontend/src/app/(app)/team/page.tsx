"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquare, Plus, Siren } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { EnvironmentBadge } from "@/components/environment-badge";
import { ReportIncidentDialog } from "@/components/report-incident-dialog";
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
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { WorkItemStatusBadge } from "@/components/work-item-status-badge";
import { ApiError, apiRequest } from "@/lib/api-client";
import {
  changeHref,
  when,
  type TeamActivity,
  type WorkItem,
  type WorkItemStatus,
} from "@/lib/team";

function message(error: unknown) {
  return error instanceof ApiError ? error.message : "Something went wrong.";
}

const FILTERS: { value: WorkItemStatus | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "open", label: "Open" },
  { value: "in_progress", label: "In progress" },
  { value: "resolved", label: "Resolved" },
  { value: "closed", label: "Closed" },
];

/**
 * The team's shared view: work items with their whole story, conversations
 * colleagues chose to share, and what changed on the TM1 servers this person
 * may use. Nothing here is visible that the person could not open anyway.
 */
export default function TeamPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<WorkItemStatus | "all">("all");
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);
  const [reporting, setReporting] = useState(false);
  const [draft, setDraft] = useState({ reference: "", title: "", description: "" });

  const items = useQuery({
    queryKey: ["team", "work-items", filter, search],
    queryFn: () => {
      const params = new URLSearchParams();
      if (filter !== "all") params.set("status", filter);
      if (search.trim()) params.set("q", search.trim());
      const qs = params.toString();
      return apiRequest<WorkItem[]>(`/team/work-items${qs ? `?${qs}` : ""}`);
    },
  });
  const activity = useQuery({
    queryKey: ["team", "activity"],
    queryFn: () => apiRequest<TeamActivity>("/team/activity"),
  });

  const create = useMutation({
    mutationFn: () =>
      apiRequest<WorkItem>("/team/work-items", {
        method: "POST",
        body: {
          reference: draft.reference,
          title: draft.title,
          description: draft.description || undefined,
        },
      }),
    onSuccess: (item) => {
      queryClient.invalidateQueries({ queryKey: ["team"] });
      setCreating(false);
      setDraft({ reference: "", title: "", description: "" });
      router.push(`/team/${item.id}`);
    },
    onError: (error) => toast.error(message(error)),
  });

  const awaiting = activity.data?.changes.filter((c) => c.awaiting_approval) ?? [];
  const recent = activity.data?.changes.filter((c) => !c.awaiting_approval).slice(0, 10) ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="page-title">Team</h1>
          <p className="text-sm text-muted-foreground">
            Work items with their whole story, conversations your colleagues shared, and what
            changed on the TM1 servers you can use.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setReporting(true)} data-tour="team-report-incident">
            <Siren className="mr-2 h-4 w-4" />
            Report incident
          </Button>
          <Button onClick={() => setCreating(true)} data-tour="team-new-work-item">
            <Plus className="mr-2 h-4 w-4" />
            New work item
          </Button>
        </div>
      </div>

      <Card data-tour="team-work-items">
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
          <div>
            <CardTitle className="text-base">Work items</CardTitle>
            <CardDescription>
              Link the investigation and the fix to a reference like PBI #1234; its timeline follows
              the change through approval and deployment.
            </CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2" data-tour="team-filters">
            <div className="flex gap-1" role="group" aria-label="Filter by status">
              {FILTERS.map((f) => (
                <Button
                  key={f.value}
                  size="sm"
                  variant={filter === f.value ? "secondary" : "ghost"}
                  aria-pressed={filter === f.value}
                  onClick={() => setFilter(f.value)}
                >
                  {f.label}
                </Button>
              ))}
            </div>
            <Input
              className="w-56"
              placeholder="Search reference or title"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              aria-label="Search work items"
            />
          </div>
        </CardHeader>
        <CardContent>
          {items.isPending ? (
            <Skeleton className="h-16 w-full" />
          ) : items.isError ? (
            <p className="text-sm text-destructive">{message(items.error)}</p>
          ) : !items.data.length ? (
            <p className="text-sm text-muted-foreground">
              No work items{filter !== "all" || search ? " match" : " yet"}.
            </p>
          ) : (
            <ul className="divide-y">
              {items.data.map((item) => (
                <li key={item.id}>
                  <Link
                    href={`/team/${item.id}`}
                    className="flex flex-wrap items-center justify-between gap-2 py-2.5 hover:bg-muted/40"
                  >
                    <span className="min-w-0">
                      {item.kind === "incident" ? (
                        <Badge variant="destructive" className="mr-1.5">incident</Badge>
                      ) : null}
                      <span className="font-medium">{item.reference}</span>{" "}
                      <span className="text-sm">{item.title}</span>
                    </span>
                    <span className="flex items-center gap-2 text-xs text-muted-foreground">
                      updated {when(item.updated_at)}
                      <WorkItemStatusBadge status={item.status} />
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card data-tour="team-awaiting">
          <CardHeader>
            <CardTitle className="text-base">Waiting for approval</CardTitle>
            <CardDescription>Drafted changes that passed validation, on servers you can use.</CardDescription>
          </CardHeader>
          <CardContent>
            {activity.isPending ? (
              <Skeleton className="h-16 w-full" />
            ) : !awaiting.length ? (
              <p className="text-sm text-muted-foreground">Nothing waiting.</p>
            ) : (
              <ul className="divide-y">
                {awaiting.map((c) => (
                  <li key={c.id} className="py-2">
                    <Link href={changeHref(c.connection_id, c.id)} className="flex flex-wrap items-center gap-2 text-sm hover:underline">
                      <EnvironmentBadge environment={c.environment} />
                      <span className="font-medium">{c.target_name}</span>
                      <span className="text-muted-foreground">
                        {c.change_type.replaceAll("_", " ")} · {c.connection_name}
                        {c.created_by_name ? ` · by ${c.created_by_name}` : ""}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card data-tour="team-shared">
          <CardHeader>
            <CardTitle className="text-base">Shared conversations</CardTitle>
            <CardDescription>
              Read-only. Share your own from the AI Assistant&apos;s history with the people icon.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {activity.isPending ? (
              <Skeleton className="h-16 w-full" />
            ) : !activity.data?.shared_conversations.length ? (
              <p className="text-sm text-muted-foreground">No one has shared a conversation yet.</p>
            ) : (
              <ul className="divide-y">
                {activity.data.shared_conversations.map((c) => (
                  <li key={c.id} className="py-2">
                    <Link href={`/team/conversations/${c.id}`} className="flex items-center gap-2 text-sm hover:underline">
                      <MessageSquare className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                      <span className="truncate">{c.title || "Untitled conversation"}</span>
                      <span className="shrink-0 text-xs text-muted-foreground">{c.owner_name}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card data-tour="team-recent">
          <CardHeader>
            <CardTitle className="text-base">Recent changes</CardTitle>
            <CardDescription>The last 14 days, on servers you can use.</CardDescription>
          </CardHeader>
          <CardContent>
            {activity.isPending ? (
              <Skeleton className="h-16 w-full" />
            ) : !recent.length ? (
              <p className="text-sm text-muted-foreground">No changes in the last 14 days.</p>
            ) : (
              <ul className="divide-y">
                {recent.map((c) => (
                  <li key={c.id} className="py-2">
                    <Link href={changeHref(c.connection_id, c.id)} className="flex flex-wrap items-center gap-2 text-sm hover:underline">
                      <EnvironmentBadge environment={c.environment} />
                      <span className="font-medium">{c.target_name}</span>
                      <Badge variant={c.status === "failed" ? "destructive" : "outline"}>{c.status.replaceAll("_", " ")}</Badge>
                      <span className="text-xs text-muted-foreground">{when(c.executed_at ?? c.created_at)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card data-tour="team-health">
          <CardHeader>
            <CardTitle className="text-base">Model health</CardTitle>
            <CardDescription>The latest scan of each server you can use.</CardDescription>
          </CardHeader>
          <CardContent>
            {activity.isPending ? (
              <Skeleton className="h-16 w-full" />
            ) : !activity.data?.health.length ? (
              <p className="text-sm text-muted-foreground">
                No scans yet. Run one on the <Link href="/health" className="underline">Model Health</Link> page.
              </p>
            ) : (
              <ul className="divide-y">
                {activity.data.health.map((h) => (
                  <li key={h.connection_id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                    <EnvironmentBadge environment={h.environment} />
                    <span className="font-medium">{h.connection_name}</span>
                    <span>
                      {h.score}/100 ({h.grade})
                    </span>
                    <span className="text-xs text-muted-foreground">{when(h.scanned_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <ReportIncidentDialog open={reporting} onOpenChange={setReporting} />

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New work item</DialogTitle>
            <DialogDescription>Use your team&apos;s own reference, so it matches your board.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="wi-reference">Reference</Label>
              <Input
                id="wi-reference"
                maxLength={50}
                placeholder="PBI #1234"
                value={draft.reference}
                onChange={(event) => setDraft({ ...draft, reference: event.target.value })}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="wi-title">Title</Label>
              <Input
                id="wi-title"
                maxLength={255}
                placeholder="Workforce load fails on the new year"
                value={draft.title}
                onChange={(event) => setDraft({ ...draft, title: event.target.value })}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="wi-description">Description (optional)</Label>
              <Textarea
                id="wi-description"
                value={draft.description}
                onChange={(event) => setDraft({ ...draft, description: event.target.value })}
              />
            </div>
            <Button
              onClick={() => create.mutate()}
              disabled={!draft.reference.trim() || !draft.title.trim() || create.isPending}
            >
              Create
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
