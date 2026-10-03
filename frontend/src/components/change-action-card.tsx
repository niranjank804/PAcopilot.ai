"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Rocket, RotateCcw, ShieldCheck, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, apiRequest } from "@/lib/api-client";
import { RunPlan } from "@/components/run-plan";
import { CHANGE_TYPE_LABEL, STATUS_VARIANT, statusLabel } from "@/lib/change-format";
import type { TM1ChangeDetail, TM1ChangeSummary } from "@/lib/types";

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong.";
}

interface ChangeActionCardProps {
  connectionId: string;
  changeId: string;
  // Deployments already renders its own status badge/target name/type as
  // part of a fuller review (diff, impact, error message) — set false there
  // to avoid showing that summary a second time. The chat inline card has
  // no other summary, so it defaults to true.
  showSummary?: boolean;
}

// Shared by /deployments and the AI Chat inline draft card so there is one
// implementation of "review a change, confirm, execute or roll it back" —
// always re-fetches the change's live status rather than trusting whatever
// state the caller last knew about, since it may have been executed
// elsewhere (another user, an earlier turn, the Deployments page directly).
export function ChangeActionCard({
  connectionId,
  changeId,
  showSummary = true,
}: ChangeActionCardProps) {
  const queryClient = useQueryClient();
  const [confirmKind, setConfirmKind] = useState<
    "execute" | "rollback" | "reject" | null
  >(null);

  const detailQuery = useQuery({
    queryKey: ["tm1-change-detail", connectionId, changeId],
    queryFn: () =>
      apiRequest<TM1ChangeDetail>(
        `/tm1/connections/${connectionId}/changes/${changeId}`,
      ),
  });

  const actionMutation = useMutation({
    mutationFn: (kind: "execute" | "rollback" | "reject") =>
      apiRequest<TM1ChangeSummary>(
        `/tm1/connections/${connectionId}/changes/${changeId}/${kind}`,
        { method: "POST" },
      ),
    onSuccess: (updated, kind) => {
      if (updated.change_type === "run_process" && kind === "execute") {
        if (updated.status === "failed") {
          toast.error(updated.error_message ?? "The process run failed.");
        } else {
          toast.success("Process ran. TM1 reported it completed successfully.");
        }
      } else if (updated.status === "failed") {
        toast.error(
          `Change ${kind} finished with verification errors — previous state was restored automatically.`,
        );
      } else if (kind === "reject") {
        toast.success("Draft discarded — never applied to the TM1 server.");
      } else {
        toast.success(
          kind === "execute"
            ? `Change executed on the TM1 server (status: ${updated.status}).`
            : "Change rolled back — previous state restored.",
        );
      }
      setConfirmKind(null);
      queryClient.invalidateQueries({
        queryKey: ["tm1-change-detail", connectionId, changeId],
      });
      queryClient.invalidateQueries({ queryKey: ["tm1-changes"] });
    },
    onError: (error) => {
      toast.error(errorMessage(error));
      setConfirmKind(null);
    },
  });

  if (detailQuery.isError) {
    return (
      <p className="max-w-md text-xs text-destructive">
        Failed to load draft: {errorMessage(detailQuery.error)}
      </p>
    );
  }

  if (detailQuery.isPending) {
    return <Skeleton className="h-16 w-full max-w-md" />;
  }

  const { change } = detailQuery.data;
  const hasErrors = Boolean(change.validation_errors?.length);
  const isRun = change.change_type === "run_process";
  const aiGenerated = Boolean(change.new_content?.ai_generated);

  return (
    <div className="max-w-md space-y-2 rounded-md border p-3">
      {showSummary ? (
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={STATUS_VARIANT[change.status]}>
            {statusLabel(change.status)}
          </Badge>
          <span className="text-sm font-medium">{change.target_name}</span>
          <span className="text-xs text-muted-foreground">
            {CHANGE_TYPE_LABEL[change.change_type]}
          </span>
        </div>
      ) : null}

      {aiGenerated ? (
        <Badge variant="outline" className="gap-1">
          <Sparkles className="h-3 w-3" />
          AI generated
        </Badge>
      ) : null}

      {/* The one screen where the product's central guarantee is either
          visible or invisible. A reviewer looking at generated TM1 needs to
          know, without asking, that the server has not been touched yet. */}
      {change.status === "draft" ? (
        <div className="rounded-md border border-primary/30 bg-primary/5 p-2.5">
          <div className="flex items-center gap-1.5">
            <ShieldCheck className="h-3.5 w-3.5 text-primary" />
            <span className="text-xs font-semibold tracking-wide text-primary">
              STET MODE
            </span>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {isRun
              ? "The process has not run. It runs only when someone with permission to run processes approves it."
              : "Nothing has been written to your TM1 server. This draft stands until someone with deploy rights executes it."}
          </p>
        </div>
      ) : null}

      {isRun ? <RunPlan change={change} /> : null}

      {hasErrors ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive">
          Validation errors — cannot be executed. Open Deployments to review.
        </div>
      ) : null}

      <div className="flex items-center gap-2">
        {change.status === "draft" && !hasErrors ? (
          <Button size="sm" onClick={() => setConfirmKind("execute")}>
            {isRun ? (
              <Play className="mr-2 h-3.5 w-3.5" />
            ) : (
              <Rocket className="mr-2 h-3.5 w-3.5" />
            )}
            {isRun ? "Review & run" : "Execute on server"}
          </Button>
        ) : null}
        {change.status === "draft" ? (
          <Button
            size="sm"
            variant="outline"
            onClick={() => setConfirmKind("reject")}
          >
            <X className="mr-2 h-3.5 w-3.5" />
            Discard
          </Button>
        ) : null}
        {change.status === "executed" && !isRun ? (
          <Button
            size="sm"
            variant="outline"
            onClick={() => setConfirmKind("rollback")}
          >
            <RotateCcw className="mr-2 h-3.5 w-3.5" />
            Roll back
          </Button>
        ) : null}
      </div>

      <AlertDialog
        open={confirmKind !== null}
        onOpenChange={(open) => {
          if (!open) setConfirmKind(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {confirmKind === "execute" && isRun
                ? `You're about to run process "${change.target_name}"`
                : confirmKind === "execute"
                ? `Execute "${change.target_name}" on the live TM1 server?`
                : confirmKind === "reject"
                  ? `Discard draft "${change.target_name}"?`
                  : `Roll back "${change.target_name}"?`}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {confirmKind === "execute" && isRun
                ? "This operation will modify TM1 data. It runs once, on the live server, with the values below, and cannot be rolled back. Your approval is audited."
                : confirmKind === "execute"
                ? "The change is applied to the live server, verified, and automatically restored if verification fails. This action is audited."
                : confirmKind === "reject"
                  ? "The draft is discarded and marked rejected. It was never applied to the live TM1 server, and this cannot be undone."
                  : "The snapshot taken at execution time will be restored on the live server. This action is audited."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {confirmKind === "execute" && isRun ? (
            <div className="max-h-72 overflow-y-auto rounded-md border p-3">
              <RunPlan change={change} />
            </div>
          ) : null}
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => confirmKind && actionMutation.mutate(confirmKind)}
              disabled={actionMutation.isPending}
              variant={confirmKind === "reject" ? "destructive" : "default"}
            >
              {actionMutation.isPending
                ? isRun && confirmKind === "execute"
                  ? "Running…"
                  : "Working..."
                : confirmKind === "execute" && isRun
                  ? "Approve & run"
                  : confirmKind === "execute"
                  ? "Execute"
                  : confirmKind === "reject"
                    ? "Discard"
                    : "Roll back"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
