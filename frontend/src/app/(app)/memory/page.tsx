"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, Check, History, Pencil, Plus, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

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
import { Textarea } from "@/components/ui/textarea";
import { ApiError, apiRequest } from "@/lib/api-client";

type Kind = "convention" | "sequence" | "caution" | "known_issue" | "note";

interface Memory {
  id: string;
  kind: Kind;
  text: string;
  status: "proposed" | "approved" | "rejected" | "archived";
  source: "human" | "ai";
  version: number;
  object_type: string | null;
  object_name: string | null;
  rationale: string | null;
  decided_at: string | null;
  created_at: string;
}

const KIND_LABEL: Record<Kind, string> = {
  convention: "Convention",
  sequence: "Run sequence",
  caution: "Caution",
  known_issue: "Known issue",
  note: "Note",
};

function message(error: unknown) {
  return error instanceof ApiError ? error.message : "Something went wrong.";
}

function MemoryText({ memory }: { memory: Memory }) {
  return (
    <div className="min-w-0 space-y-1">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant="outline">{KIND_LABEL[memory.kind]}</Badge>
        {memory.object_name ? (
          <Badge variant="secondary">
            {memory.object_type} {memory.object_name}
          </Badge>
        ) : null}
        {memory.source === "ai" ? (
          <Badge variant="outline" className="gap-1">
            <Sparkles className="h-3 w-3" aria-hidden />
            suggested by the assistant
          </Badge>
        ) : null}
        {memory.version > 1 ? <span className="text-xs text-muted-foreground">v{memory.version}</span> : null}
      </div>
      <p className="text-sm">{memory.text}</p>
      {memory.rationale ? (
        <p className="text-xs text-muted-foreground">Why: {memory.rationale}</p>
      ) : null}
    </div>
  );
}

/**
 * What the team knows about its TM1 model that the model itself cannot say.
 * Approved entries go to the assistant in every conversation; the
 * assistant's own suggestions wait here until someone approves them.
 */
export default function MemoryPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState<{ kind: Kind; text: string; object_type: string; object_name: string }>({
    kind: "sequence",
    text: "",
    object_type: "",
    object_name: "",
  });
  const [editing, setEditing] = useState<Memory | null>(null);
  const [editText, setEditText] = useState("");
  const [historyOf, setHistoryOf] = useState<Memory | null>(null);

  const proposals = useQuery({
    queryKey: ["memory", "proposed"],
    queryFn: () => apiRequest<Memory[]>("/knowledge/memory?status=proposed"),
  });
  const approved = useQuery({
    queryKey: ["memory", "approved", search],
    queryFn: () =>
      apiRequest<Memory[]>(
        `/knowledge/memory?status=approved${search.trim() ? `&q=${encodeURIComponent(search.trim())}` : ""}`,
      ),
  });
  const history = useQuery({
    queryKey: ["memory", "history", historyOf?.id],
    queryFn: () => apiRequest<Memory[]>(`/knowledge/memory/${historyOf?.id}/history`),
    enabled: Boolean(historyOf),
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["memory"] });

  const act = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "approve" | "reject" | "archive" }) =>
      apiRequest(`/knowledge/memory/${id}/${action}`, { method: "POST" }),
    onSuccess: (_d, { action }) => {
      toast.success(
        action === "approve"
          ? "Approved — the assistant uses it from the next message."
          : action === "reject"
            ? "Rejected."
            : "Archived — the assistant no longer uses it.",
      );
      refresh();
    },
    onError: (error) => toast.error(message(error)),
  });

  const add = useMutation({
    mutationFn: () =>
      apiRequest<Memory>("/knowledge/memory", {
        method: "POST",
        body: {
          kind: draft.kind,
          text: draft.text,
          object_type: draft.object_type || undefined,
          object_name: draft.object_name || undefined,
        },
      }),
    onSuccess: (memory) => {
      toast.success(memory.status === "approved" ? "Saved and in use." : "Saved as a proposal for approval.");
      setAdding(false);
      setDraft({ kind: "sequence", text: "", object_type: "", object_name: "" });
      refresh();
    },
    onError: (error) => toast.error(message(error)),
  });

  const edit = useMutation({
    mutationFn: () =>
      apiRequest<Memory>(`/knowledge/memory/${editing?.id}`, { method: "PUT", body: { text: editText } }),
    onSuccess: () => {
      toast.success("Saved as a new version; the old one is kept in history.");
      setEditing(null);
      refresh();
    },
    onError: (error) => toast.error(message(error)),
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="page-title">Engineering Memory</h1>
          <p className="text-sm text-muted-foreground">
            What your team knows about the model that TM1 cannot say — run sequences, conventions,
            cautions, known issues. Approved entries go to the assistant in every conversation; its
            own suggestions wait here for a person.
          </p>
        </div>
        <Button onClick={() => setAdding(true)}>
          <Plus className="mr-2 h-4 w-4" />
          Add memory
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Waiting for approval</CardTitle>
          <CardDescription>Not used by the assistant until approved.</CardDescription>
        </CardHeader>
        <CardContent>
          {proposals.isPending ? (
            <Skeleton className="h-16 w-full" />
          ) : !proposals.data?.length ? (
            <p className="text-sm text-muted-foreground">Nothing waiting.</p>
          ) : (
            <ul className="divide-y">
              {proposals.data.map((m) => (
                <li key={m.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
                  <MemoryText memory={m} />
                  <div className="flex shrink-0 gap-2">
                    <Button size="sm" onClick={() => act.mutate({ id: m.id, action: "approve" })} disabled={act.isPending}>
                      <Check className="mr-1 h-3.5 w-3.5" />
                      Approve
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => act.mutate({ id: m.id, action: "reject" })} disabled={act.isPending}>
                      <X className="mr-1 h-3.5 w-3.5" />
                      Reject
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
          <div>
            <CardTitle className="text-base">In use</CardTitle>
            <CardDescription>The assistant follows these and cites them as organization knowledge.</CardDescription>
          </div>
          <Input
            className="w-64"
            placeholder="Search by object or words"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            aria-label="Search memory"
          />
        </CardHeader>
        <CardContent>
          {approved.isPending ? (
            <Skeleton className="h-16 w-full" />
          ) : !approved.data?.length ? (
            <p className="text-sm text-muted-foreground">No approved memory yet.</p>
          ) : (
            <ul className="divide-y">
              {approved.data.map((m) => (
                <li key={m.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
                  <MemoryText memory={m} />
                  <div className="flex shrink-0 gap-1">
                    <Button size="sm" variant="ghost" aria-label="Edit" onClick={() => { setEditing(m); setEditText(m.text); }}>
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button size="sm" variant="ghost" aria-label="History" onClick={() => setHistoryOf(m)}>
                      <History className="h-3.5 w-3.5" />
                    </Button>
                    <Button size="sm" variant="ghost" aria-label="Archive" onClick={() => act.mutate({ id: m.id, action: "archive" })}>
                      <Archive className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Dialog open={adding} onOpenChange={setAdding}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add memory</DialogTitle>
            <DialogDescription>
              With knowledge rights it is in use at once; otherwise it waits for approval.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="memory-kind">Kind</Label>
              <Select value={draft.kind} onValueChange={(value) => value && setDraft({ ...draft, kind: value as Kind })}>
                <SelectTrigger id="memory-kind" className="w-full">
                  <SelectValue>{(value: Kind) => KIND_LABEL[value]}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(KIND_LABEL) as Kind[]).map((k) => (
                    <SelectItem key={k} value={k}>
                      {KIND_LABEL[k]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="memory-text">What should the assistant know?</Label>
              <Textarea
                id="memory-text"
                value={draft.text}
                maxLength={1000}
                onChange={(event) => setDraft({ ...draft, text: event.target.value })}
                placeholder="e.g. Load Rates must finish before Load Sales starts."
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label htmlFor="memory-object-type">About (optional)</Label>
                <Select
                  value={draft.object_type || "none"}
                  onValueChange={(value) => setDraft({ ...draft, object_type: value === "none" || !value ? "" : value })}
                >
                  <SelectTrigger id="memory-object-type" className="w-full">
                    <SelectValue>{(value: string) => (value === "none" ? "Whole model" : value)}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {["none", "cube", "dimension", "process", "chore", "rule"].map((t) => (
                      <SelectItem key={t} value={t}>
                        {t === "none" ? "Whole model" : t}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="memory-object-name">Object name</Label>
                <Input
                  id="memory-object-name"
                  value={draft.object_name}
                  disabled={!draft.object_type}
                  onChange={(event) => setDraft({ ...draft, object_name: event.target.value })}
                />
              </div>
            </div>
            <Button onClick={() => add.mutate()} disabled={!draft.text.trim() || add.isPending}>
              Save
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={editing !== null} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit memory</DialogTitle>
            <DialogDescription>Saved as a new version; the current one stays in history.</DialogDescription>
          </DialogHeader>
          <Textarea value={editText} maxLength={1000} onChange={(event) => setEditText(event.target.value)} aria-label="Memory text" />
          <Button onClick={() => edit.mutate()} disabled={!editText.trim() || edit.isPending}>
            Save new version
          </Button>
        </DialogContent>
      </Dialog>

      <Dialog open={historyOf !== null} onOpenChange={(open) => !open && setHistoryOf(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>History</DialogTitle>
            <DialogDescription>Every version, newest first.</DialogDescription>
          </DialogHeader>
          {history.isPending ? (
            <Skeleton className="h-16 w-full" />
          ) : (
            <ol className="space-y-2 text-sm">
              {history.data?.map((v) => (
                <li key={v.id}>
                  <span className="font-medium">v{v.version}</span>{" "}
                  <span className="text-muted-foreground">
                    ({v.status}, {new Date(v.created_at).toLocaleDateString()})
                  </span>{" "}
                  {v.text}
                </li>
              ))}
            </ol>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
