"use client";

import { useQuery } from "@tanstack/react-query";
import { Download, History } from "lucide-react";
import { useState } from "react";

import { ExecutionStatusBadge } from "@/components/report-status-badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiRequest } from "@/lib/api-client";
import type {
  ReportExecution,
  ReportExecutionDetail,
} from "@/lib/report-types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function duration(ms: number | null) {
  if (ms === null) return "—";

  if (ms < 1000) return `${ms}ms`;

  const seconds = Math.round(ms / 100) / 10;

  return seconds < 60 ? `${seconds}s` : `${Math.round(seconds / 60)}m`;
}

export default function ExecutionsPage() {
  const [selected, setSelected] = useState<string | null>(null);

  const executions = useQuery({
    queryKey: ["report-executions"],
    queryFn: () => apiRequest<ReportExecution[]>("/reports/executions"),
    // Executions move through states on a worker's schedule, not the
    // browser's, so the list polls while it is open.
    refetchInterval: 5000,
  });

  const detail = useQuery({
    queryKey: ["report-execution", selected],
    queryFn: () =>
      apiRequest<ReportExecutionDetail>(`/reports/executions/${selected}`),
    enabled: selected !== null,
  });

  /** Downloads go through an authenticated request, not a bare link — an
   * artifact id is an identifier, not a capability. */
  async function downloadArtifact(artifactId: string, filename: string) {
    const token = localStorage.getItem("accessToken");

    const response = await fetch(
      `${API_URL}/reports/artifacts/${artifactId}/download`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} },
    );

    if (!response.ok) return;

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");

    anchor.href = url;
    anchor.download = filename;
    anchor.click();

    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Execution history
        </h1>
        <p className="text-sm text-muted-foreground">
          Every report run, including retries and failures.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Executions</CardTitle>
          <CardDescription>
            A retry is a new execution linked to the one it replaces, so the
            history of what actually happened stays intact.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {executions.isLoading ? (
            <Skeleton className="h-24 w-full" />
          ) : executions.data?.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Execution</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Trigger</TableHead>
                  <TableHead>Attempt</TableHead>
                  <TableHead>Queued</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead>Error</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {executions.data.map((execution) => (
                  <TableRow
                    key={execution.id}
                    className="cursor-pointer"
                    onClick={() => setSelected(execution.id)}
                  >
                    <TableCell className="font-mono text-xs">
                      {execution.id.slice(0, 8)}
                    </TableCell>
                    <TableCell>
                      <ExecutionStatusBadge status={execution.status} />
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {execution.trigger_type}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {execution.attempt}/{execution.max_attempts}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {new Date(execution.queued_at).toLocaleString()}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {duration(execution.duration_ms)}
                    </TableCell>
                    <TableCell className="max-w-xs truncate text-xs text-muted-foreground">
                      {execution.error_message ?? "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="py-10 text-center text-sm text-muted-foreground">
              <History className="mx-auto mb-3 h-8 w-8 opacity-40" />
              No executions yet.
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={selected !== null} onOpenChange={() => setSelected(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Execution detail</DialogTitle>
            <DialogDescription className="font-mono text-xs">
              {selected}
            </DialogDescription>
          </DialogHeader>

          {detail.isLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : detail.data ? (
            <div className="space-y-4 text-sm">
              <dl className="grid grid-cols-2 gap-2">
                <dt className="text-muted-foreground">Status</dt>
                <dd>
                  <ExecutionStatusBadge status={detail.data.status} />
                </dd>

                <dt className="text-muted-foreground">Correlation id</dt>
                <dd className="font-mono text-xs">
                  {detail.data.correlation_id}
                </dd>

                <dt className="text-muted-foreground">Started</dt>
                <dd>
                  {detail.data.started_at
                    ? new Date(detail.data.started_at).toLocaleString()
                    : "—"}
                </dd>

                <dt className="text-muted-foreground">Completed</dt>
                <dd>
                  {detail.data.completed_at
                    ? new Date(detail.data.completed_at).toLocaleString()
                    : "—"}
                </dd>

                <dt className="text-muted-foreground">Duration</dt>
                <dd>{duration(detail.data.duration_ms)}</dd>

                {detail.data.error_code && (
                  <>
                    <dt className="text-muted-foreground">Error code</dt>
                    <dd className="font-mono text-xs">
                      {detail.data.error_code} ({detail.data.retry_class})
                    </dd>
                  </>
                )}
              </dl>

              {detail.data.artifacts.length > 0 && (
                <div>
                  <h3 className="mb-2 font-medium">Artifacts</h3>
                  <div className="space-y-2">
                    {detail.data.artifacts.map((artifact) => (
                      <div
                        key={artifact.id}
                        className="flex items-center justify-between rounded-md border p-2"
                      >
                        <div>
                          <div className="text-sm">{artifact.filename}</div>
                          <div className="text-xs text-muted-foreground">
                            {(artifact.size_bytes / 1024).toFixed(1)} KB ·
                            sha256 {artifact.checksum.slice(0, 12)}…
                          </div>
                        </div>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            downloadArtifact(artifact.id, artifact.filename)
                          }
                        >
                          <Download className="mr-2 h-3 w-3" />
                          Download
                        </Button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {detail.data.trace_log && (
                <div>
                  <h3 className="mb-2 font-medium">
                    PAfE automation trace log
                  </h3>
                  <pre className="max-h-48 overflow-auto rounded-md bg-muted p-3 text-xs">
                    {detail.data.trace_log}
                  </pre>
                </div>
              )}
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
