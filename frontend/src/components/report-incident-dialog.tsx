"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
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
import { Textarea } from "@/components/ui/textarea";
import { ApiError, apiRequest } from "@/lib/api-client";
import { USABLE_CONNECTIONS_KEY, fetchUsableConnections } from "@/lib/connections";
import type { IncidentSeverity, WorkItemDetail } from "@/lib/team";

const SEVERITIES: IncidentSeverity[] = ["critical", "high", "medium", "low"];
const WINDOWS = [
  { hours: 24, label: "Last 24 hours" },
  { hours: 48, label: "Last 48 hours" },
  { hours: 168, label: "Last 7 days" },
];

const EMPTY = {
  reference: "",
  title: "",
  description: "",
  connection: "",
  cube: "",
  process: "",
  severity: "high" as IncidentSeverity,
  window: 48,
};

/**
 * "Production allocation is wrong": say where, and PA-Copilot looks at once
 * — what changed, what ran, what failed near it — and opens the incident.
 */
export function ReportIncidentDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(EMPTY);
  const connections = useQuery({ queryKey: USABLE_CONNECTIONS_KEY, queryFn: fetchUsableConnections, enabled: open });
  const byId = new Map((connections.data ?? []).map((c) => [c.id, c]));

  const report = useMutation({
    mutationFn: () =>
      apiRequest<WorkItemDetail>("/team/incidents", {
        method: "POST",
        body: {
          reference: draft.reference,
          title: draft.title,
          description: draft.description || undefined,
          connection_id: draft.connection,
          severity: draft.severity,
          cube_name: draft.cube || undefined,
          process_name: draft.process || undefined,
          window_hours: draft.window,
        },
      }),
    onSuccess: (detail) => {
      queryClient.invalidateQueries({ queryKey: ["team"] });
      onOpenChange(false);
      setDraft(EMPTY);
      router.push(`/team/${detail.item.id}`);
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : "Something went wrong."),
  });

  const ready =
    draft.reference.trim() && draft.title.trim() && draft.connection && (draft.cube.trim() || draft.process.trim());

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Report an incident</DialogTitle>
          <DialogDescription>
            PA-Copilot looks at once — recent changes, runs, failures and model differences near
            it — and ranks what most likely caused it. It only reads.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="grid grid-cols-[8rem_1fr] gap-2">
            <div className="space-y-1">
              <Label htmlFor="inc-reference">Reference</Label>
              <Input id="inc-reference" maxLength={50} placeholder="INC-42" value={draft.reference}
                onChange={(e) => setDraft({ ...draft, reference: e.target.value })} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="inc-title">What is wrong</Label>
              <Input id="inc-title" maxLength={255} placeholder="Production allocation is wrong" value={draft.title}
                onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
            </div>
          </div>
          <div className="space-y-1">
            <Label htmlFor="inc-server">Server</Label>
            <Select value={draft.connection} onValueChange={(value) => setDraft({ ...draft, connection: value ?? "" })}>
              <SelectTrigger id="inc-server" className="w-full">
                <SelectValue placeholder="Choose a server">
                  {(value: string) => {
                    const c = byId.get(value);
                    return c ? `${c.name} (${(c.environment ?? "dev").toUpperCase()})` : "Choose a server";
                  }}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {(connections.data ?? []).map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    {c.name} ({(c.environment ?? "dev").toUpperCase()})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <Label htmlFor="inc-cube">Cube that looks wrong</Label>
              <Input id="inc-cube" placeholder="Allocation" value={draft.cube}
                onChange={(e) => setDraft({ ...draft, cube: e.target.value })} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="inc-process">or process that failed</Label>
              <Input id="inc-process" placeholder="Load Allocation" value={draft.process}
                onChange={(e) => setDraft({ ...draft, process: e.target.value })} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <Label htmlFor="inc-severity">Severity</Label>
              <Select value={draft.severity} onValueChange={(value) => value && setDraft({ ...draft, severity: value as IncidentSeverity })}>
                <SelectTrigger id="inc-severity" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SEVERITIES.map((s) => (
                    <SelectItem key={s} value={s}>
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="inc-window">Look back</Label>
              <Select value={String(draft.window)} onValueChange={(value) => value && setDraft({ ...draft, window: Number(value) })}>
                <SelectTrigger id="inc-window" className="w-full">
                  <SelectValue>{(value: string) => WINDOWS.find((w) => String(w.hours) === value)?.label}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {WINDOWS.map((w) => (
                    <SelectItem key={w.hours} value={String(w.hours)}>
                      {w.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="space-y-1">
            <Label htmlFor="inc-description">Details (optional)</Label>
            <Textarea id="inc-description" value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
          </div>
          <Button onClick={() => report.mutate()} disabled={!ready || report.isPending}>
            {report.isPending ? "Investigating…" : "Report and investigate"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
