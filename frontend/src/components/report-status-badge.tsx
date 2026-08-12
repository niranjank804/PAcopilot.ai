"use client";

import { Badge } from "@/components/ui/badge";
import type { ExecutionStatus, WorkerStatus } from "@/lib/report-types";

/** Terminal failures read as destructive; in-flight states read as neutral
 * so a queue full of running jobs does not look like a queue full of
 * problems. */
const EXECUTION_VARIANTS: Record<
  ExecutionStatus,
  "default" | "secondary" | "destructive" | "outline"
> = {
  queued: "outline",
  assigned: "outline",
  running: "secondary",
  retrying: "secondary",
  succeeded: "default",
  failed: "destructive",
  timed_out: "destructive",
  cancelled: "outline",
};

const WORKER_VARIANTS: Record<
  WorkerStatus,
  "default" | "secondary" | "destructive" | "outline"
> = {
  online: "default",
  busy: "secondary",
  offline: "outline",
  pending_enrollment: "outline",
  disabled: "destructive",
  error: "destructive",
};

function humanize(value: string) {
  return value.replace(/_/g, " ");
}

export function ExecutionStatusBadge({ status }: { status: ExecutionStatus }) {
  return (
    <Badge variant={EXECUTION_VARIANTS[status] ?? "outline"}>
      {humanize(status)}
    </Badge>
  );
}

export function WorkerStatusBadge({ status }: { status: WorkerStatus }) {
  return (
    <Badge variant={WORKER_VARIANTS[status] ?? "outline"}>
      {humanize(status)}
    </Badge>
  );
}
