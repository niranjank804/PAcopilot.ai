"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Loader2, Plus, Server, ShieldOff } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { WorkerStatusBadge } from "@/components/report-status-badge";
import { Badge } from "@/components/ui/badge";
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
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, apiRequest } from "@/lib/api-client";
import type { ReportWorker, WorkerEnrollment } from "@/lib/report-types";

function relativeTime(value: string | null) {
  if (!value) return "never";

  const seconds = Math.floor((Date.now() - new Date(value).getTime()) / 1000);

  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;

  return `${Math.floor(seconds / 86400)}d ago`;
}

export default function WorkersPage() {
  const queryClient = useQueryClient();

  const [registerOpen, setRegisterOpen] = useState(false);
  const [name, setName] = useState("");
  const [enrollment, setEnrollment] = useState<WorkerEnrollment | null>(null);

  const workers = useQuery({
    queryKey: ["report-workers"],
    queryFn: () => apiRequest<ReportWorker[]>("/reports/workers"),
    // Status is derived from the heartbeat clock, so it goes stale on its
    // own without a refetch.
    refetchInterval: 15000,
  });

  const register = useMutation({
    mutationFn: () =>
      apiRequest<WorkerEnrollment>("/reports/workers", {
        method: "POST",
        body: { name },
      }),
    onSuccess: (data) => {
      setEnrollment(data);
      setRegisterOpen(false);
      setName("");
      queryClient.invalidateQueries({ queryKey: ["report-workers"] });
    },
    onError: (error: ApiError) => toast.error(error.message),
  });

  const setEnabled = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      apiRequest<ReportWorker>(
        `/reports/workers/${id}/${enabled ? "enable" : "disable"}`,
        { method: "POST" },
      ),
    onSuccess: () => {
      toast.success("Worker updated");
      queryClient.invalidateQueries({ queryKey: ["report-workers"] });
    },
    onError: (error: ApiError) => toast.error(error.message),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Report workers
          </h1>
          <p className="text-sm text-muted-foreground">
            Windows machines running Excel and PAfE that execute your reports.
          </p>
        </div>

        <Button onClick={() => setRegisterOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          Register worker
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Registered workers</CardTitle>
          <CardDescription>
            Capabilities are verified by the worker itself — a worker is only
            given work it has proved it can do.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {workers.isLoading ? (
            <Skeleton className="h-24 w-full" />
          ) : workers.data?.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Worker</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Excel</TableHead>
                  <TableHead>PAfE</TableHead>
                  <TableHead>Capabilities</TableHead>
                  <TableHead>Last heartbeat</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {workers.data.map((worker) => (
                  <TableRow key={worker.id}>
                    <TableCell>
                      <div className="font-medium">{worker.name}</div>
                      <div className="text-xs text-muted-foreground">
                        {worker.hostname ?? "—"} · {worker.os ?? "—"}
                      </div>
                    </TableCell>
                    <TableCell>
                      <WorkerStatusBadge status={worker.status} />
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {worker.excel_version ?? "—"}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {worker.pafe_version ?? "not detected"}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {worker.capabilities.length ? (
                          worker.capabilities.map((capability) => (
                            <Badge
                              key={capability}
                              variant="secondary"
                              className="text-xs"
                            >
                              {capability}
                            </Badge>
                          ))
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            none verified
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {relativeTime(worker.last_heartbeat_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          setEnabled.mutate({
                            id: worker.id,
                            enabled: worker.status === "disabled",
                          })
                        }
                      >
                        <ShieldOff className="mr-2 h-3 w-3" />
                        {worker.status === "disabled" ? "Enable" : "Disable"}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="py-10 text-center text-sm text-muted-foreground">
              <Server className="mx-auto mb-3 h-8 w-8 opacity-40" />
              No workers registered yet.
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={registerOpen} onOpenChange={setRegisterOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Register a worker</DialogTitle>
            <DialogDescription>
              You will get a single-use enrollment token to run on the Windows
              machine.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-2">
            <Label htmlFor="worker-name">Worker name</Label>
            <Input
              id="worker-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="finance-reporting-01"
            />
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setRegisterOpen(false)}>
              Cancel
            </Button>
            <Button
              disabled={!name || register.isPending}
              onClick={() => register.mutate()}
            >
              {register.isPending && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              )}
              Register
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Shown once. The token is stored only as a keyed digest, so it
          cannot be retrieved again from anywhere. */}
      <Dialog
        open={enrollment !== null}
        onOpenChange={() => setEnrollment(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Enrollment token</DialogTitle>
            <DialogDescription>
              This is shown once and cannot be retrieved again. It is
              single-use and expires.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <code className="block overflow-x-auto rounded-md bg-muted p-3 text-xs">
              {enrollment?.enrollment_token}
            </code>

            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                navigator.clipboard.writeText(
                  enrollment?.enrollment_token ?? "",
                );
                toast.success("Copied");
              }}
            >
              <Copy className="mr-2 h-3 w-3" />
              Copy
            </Button>

            <p className="text-sm text-muted-foreground">
              {enrollment?.instructions}
            </p>
          </div>

          <DialogFooter>
            <Button onClick={() => setEnrollment(null)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
