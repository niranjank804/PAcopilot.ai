"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, Circle, Link2, MessageSquare, Rocket, Unlink } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
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
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { WorkItemStatusBadge } from "@/components/work-item-status-badge";
import { ApiError, apiRequest } from "@/lib/api-client";
import {
  STATUS_LABEL,
  changeHref,
  when,
  type SharedConversation,
  type TeamActivity,
  type WorkItemDetail,
  type WorkItemStatus,
} from "@/lib/team";
import { cn } from "@/lib/utils";

function message(error: unknown) {
  return error instanceof ApiError ? error.message : "Something went wrong.";
}

function WrittenField({
  id,
  label,
  hint,
  value,
  saving,
  onSave,
}: {
  id: string;
  label: string;
  hint: string;
  value: string | null;
  saving: boolean;
  onSave: (text: string) => void;
}) {
  // Remounted (keyed by the saved value) when a save lands, so the draft
  // starts again from what was saved.
  const [text, setText] = useState(value ?? "");
  const dirty = text.trim() !== (value ?? "").trim();

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Textarea id={id} value={text} placeholder={hint} onChange={(event) => setText(event.target.value)} />
      {dirty ? (
        <Button size="sm" onClick={() => onSave(text)} disabled={saving}>
          Save {label.toLowerCase()}
        </Button>
      ) : null}
    </div>
  );
}

/**
 * One work item's story, read from the records linked to it: who
 * investigated, what the root cause was, the change that fixed it, who
 * approved and applied it, and how it ended. Records this person cannot
 * open are shown as such, without their detail.
 */
export default function WorkItemPage() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const [linking, setLinking] = useState(false);
  const [linkKind, setLinkKind] = useState<"conversation" | "change">("conversation");
  const [linkTarget, setLinkTarget] = useState("");
  const [linkNote, setLinkNote] = useState("");

  const detail = useQuery({
    queryKey: ["team", "work-item", id],
    queryFn: () => apiRequest<WorkItemDetail>(`/team/work-items/${id}`),
  });
  const conversations = useQuery({
    queryKey: ["team", "conversations"],
    queryFn: () => apiRequest<SharedConversation[]>("/team/conversations"),
    enabled: linking,
  });
  const changes = useQuery({
    queryKey: ["team", "activity", 90],
    queryFn: () => apiRequest<TeamActivity>("/team/activity?days=90"),
    enabled: linking,
  });

  const setDetail = (data: WorkItemDetail) => {
    queryClient.setQueryData(["team", "work-item", id], data);
    queryClient.invalidateQueries({ queryKey: ["team", "work-items"] });
  };

  const update = useMutation({
    mutationFn: (body: Partial<Record<"status" | "root_cause" | "resolution", string>>) =>
      apiRequest<WorkItemDetail>(`/team/work-items/${id}`, { method: "PATCH", body }),
    onSuccess: (data) => {
      setDetail(data);
      toast.success("Saved.");
    },
    onError: (error) => toast.error(message(error)),
  });

  const link = useMutation({
    mutationFn: () =>
      apiRequest<WorkItemDetail>(`/team/work-items/${id}/links`, {
        method: "POST",
        body: { kind: linkKind, target_id: linkTarget, note: linkNote.trim() || undefined },
      }),
    onSuccess: (data) => {
      setDetail(data);
      setLinking(false);
      setLinkTarget("");
      setLinkNote("");
      toast.success("Linked.");
    },
    onError: (error) => toast.error(message(error)),
  });

  const unlink = useMutation({
    mutationFn: (linkId: string) =>
      apiRequest<WorkItemDetail>(`/team/work-items/${id}/links/${linkId}`, { method: "DELETE" }),
    onSuccess: (data) => {
      setDetail(data);
      toast.success("Unlinked.");
    },
    onError: (error) => toast.error(message(error)),
  });

  if (detail.isPending) return <Skeleton className="h-64 w-full" />;
  if (detail.isError) {
    return <p className="text-sm text-destructive">{message(detail.error)}</p>;
  }

  const { item, progress, links, events } = detail.data;
  const linkedIds = new Set(links.map((l) => l.target_id));
  const options =
    linkKind === "conversation"
      ? (conversations.data ?? [])
          .filter((c) => !linkedIds.has(c.id))
          .map((c) => ({ id: c.id, label: `${c.title || "Untitled conversation"} — ${c.owner_name}` }))
      : (changes.data?.changes ?? [])
          .filter((c) => !linkedIds.has(c.id))
          .map((c) => ({
            id: c.id,
            label: `${c.target_name} · ${c.change_type.replaceAll("_", " ")} · ${c.connection_name} (${c.environment.toUpperCase()}) · ${c.status}`,
          }));

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Link href="/team" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-3.5 w-3.5" />
          Team
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="page-title">
              {item.reference} <span className="font-normal">{item.title}</span>
            </h1>
            <p className="text-sm text-muted-foreground">
              Opened {when(item.created_at)}
              {detail.data.created_by_name ? ` by ${detail.data.created_by_name}` : ""}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <WorkItemStatusBadge status={item.status} />
            <Select
              value={item.status}
              onValueChange={(value) => value && value !== item.status && update.mutate({ status: value })}
            >
              <SelectTrigger className="w-40" aria-label="Status">
                <SelectValue>{(value: WorkItemStatus) => STATUS_LABEL[value]}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(STATUS_LABEL) as WorkItemStatus[]).map((s) => (
                  <SelectItem key={s} value={s}>
                    {STATUS_LABEL[s]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        {item.description ? <p className="max-w-3xl whitespace-pre-wrap text-sm">{item.description}</p> : null}
      </div>

      <ol className="flex flex-wrap gap-x-4 gap-y-2" aria-label="Progress">
        {progress.map((step) => (
          <li key={step.key} className={cn("flex items-center gap-1.5 text-sm", !step.done && "text-muted-foreground")}>
            {step.done ? (
              <CheckCircle2 className="h-4 w-4 text-primary" aria-hidden />
            ) : (
              <Circle className="h-4 w-4" aria-hidden />
            )}
            {step.label}
            <span className="sr-only">{step.done ? "done" : "not yet"}</span>
          </li>
        ))}
      </ol>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">What the team found</CardTitle>
            <CardDescription>Written by people; the timeline records who and when.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <WrittenField
              key={item.root_cause ?? ""}
              id="wi-root-cause"
              label="Root cause"
              hint="e.g. The Year dimension has no 2027 element, so the lookup fails."
              value={item.root_cause}
              saving={update.isPending}
              onSave={(text) => update.mutate({ root_cause: text })}
            />
            <WrittenField
              key={item.resolution ?? ""}
              id="wi-resolution"
              label="Resolution"
              hint="e.g. Added 2027 to Year and re-ran the load; verified totals in Workforce."
              value={item.resolution}
              saving={update.isPending}
              onSave={(text) => update.mutate({ resolution: text })}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
            <div>
              <CardTitle className="text-base">Linked</CardTitle>
              <CardDescription>Shared conversations and TM1 changes.</CardDescription>
            </div>
            <Button size="sm" variant="outline" onClick={() => setLinking(true)}>
              <Link2 className="mr-1 h-3.5 w-3.5" />
              Link
            </Button>
          </CardHeader>
          <CardContent>
            {!links.length ? (
              <p className="text-sm text-muted-foreground">
                Nothing linked yet. Link the conversation where the problem was investigated and the
                change that fixes it.
              </p>
            ) : (
              <ul className="divide-y">
                {links.map((l) => (
                  <li key={l.link_id} className="flex items-start justify-between gap-2 py-2.5">
                    <div className="min-w-0 space-y-0.5 text-sm">
                      <div className="flex flex-wrap items-center gap-2">
                        {l.kind === "conversation" ? (
                          <MessageSquare className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                        ) : (
                          <Rocket className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                        )}
                        {!l.available ? (
                          <span className="text-muted-foreground">{l.title}</span>
                        ) : l.kind === "conversation" ? (
                          <Link href={`/team/conversations/${l.target_id}`} className="font-medium hover:underline">
                            {l.title}
                          </Link>
                        ) : (
                          <Link
                            href={changeHref(l.connection_id ?? "", l.target_id)}
                            className="font-medium hover:underline"
                          >
                            {l.title}
                          </Link>
                        )}
                        {l.environment ? <EnvironmentBadge environment={l.environment} /> : null}
                        {l.status ? <Badge variant="outline">{l.status.replaceAll("_", " ")}</Badge> : null}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {l.kind === "conversation" && l.available
                          ? `${l.owner_name ?? "Someone"} · ${l.messages ?? 0} messages · `
                          : l.connection_name
                            ? `${l.connection_name} · `
                            : ""}
                        linked by {l.linked_by_name ?? "someone"}
                      </p>
                      {l.note ? <p className="text-xs">{l.note}</p> : null}
                    </div>
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label="Unlink"
                      disabled={unlink.isPending}
                      onClick={() => unlink.mutate(l.link_id)}
                    >
                      <Unlink className="h-3.5 w-3.5" />
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Timeline</CardTitle>
          <CardDescription>From the records as they are now, oldest first.</CardDescription>
        </CardHeader>
        <CardContent>
          <ol className="relative space-y-4 border-l pl-5">
            {events.map((e, index) => (
              <li key={`${e.at}-${index}`} className="relative">
                <span
                  className={cn(
                    "absolute -left-[26px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-background",
                    e.kind.endsWith("failed") || e.title.includes("failed")
                      ? "bg-destructive"
                      : e.kind === "unavailable"
                        ? "bg-muted-foreground/40"
                        : "bg-primary",
                  )}
                  aria-hidden
                />
                <p className="text-sm font-medium">{e.title}</p>
                <p className="text-xs text-muted-foreground">
                  {when(e.at)}
                  {e.actor ? ` · ${e.actor}` : ""}
                </p>
                {e.detail ? <p className="mt-0.5 whitespace-pre-wrap text-sm">{e.detail}</p> : null}
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>

      <Dialog open={linking} onOpenChange={setLinking}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Link to {item.reference}</DialogTitle>
            <DialogDescription>
              Only shared conversations can be linked. Changes are listed from the last 90 days on
              servers you can use.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="flex gap-1" role="group" aria-label="What to link">
              {(["conversation", "change"] as const).map((kind) => (
                <Button
                  key={kind}
                  size="sm"
                  variant={linkKind === kind ? "secondary" : "ghost"}
                  aria-pressed={linkKind === kind}
                  onClick={() => {
                    setLinkKind(kind);
                    setLinkTarget("");
                  }}
                >
                  {kind === "conversation" ? "Conversation" : "TM1 change"}
                </Button>
              ))}
            </div>
            {(linkKind === "conversation" ? conversations.isPending : changes.isPending) ? (
              <Skeleton className="h-9 w-full" />
            ) : !options.length ? (
              <p className="text-sm text-muted-foreground">
                {linkKind === "conversation"
                  ? "No shared conversations to link. Share one from the AI Assistant's history first."
                  : "No changes from the last 90 days to link."}
              </p>
            ) : (
              <Select value={linkTarget} onValueChange={(value) => setLinkTarget(value ?? "")}>
                <SelectTrigger className="w-full" aria-label="Choose what to link">
                  <SelectValue placeholder="Choose…">
                    {(value: string) => options.find((o) => o.id === value)?.label ?? "Choose…"}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {options.map((o) => (
                    <SelectItem key={o.id} value={o.id}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            <div className="space-y-1">
              <Label htmlFor="link-note">Note (optional)</Label>
              <Textarea
                id="link-note"
                maxLength={2000}
                placeholder="e.g. The investigation that found the missing element."
                value={linkNote}
                onChange={(event) => setLinkNote(event.target.value)}
              />
            </div>
            <Button onClick={() => link.mutate()} disabled={!linkTarget || link.isPending}>
              Link
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
