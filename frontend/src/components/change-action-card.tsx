"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Rocket, RotateCcw } from "lucide-react";
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
import { CHANGE_TYPE_LABEL, STATUS_VARIANT } from "@/lib/change-format";
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
  const [confirmKind, setConfirmKind] = useState<"execute" | "rollback" | null>(null);

  const detailQuery = useQuery({
    queryKey: ["tm1-change-detail", connectionId, changeId],
    queryFn: () =>
      apiRequest<TM1ChangeDetail>(
        `/tm1/connections/${connectionId}/changes/${changeId}`,
      ),
  });

  const actionMutation = useMutation({
    mutationFn: (kind: "execute" | "rollback") =>
      apiRequest<TM1ChangeSummary>(
        `/tm1/connections/${connectionId}/changes/${changeId}/${kind}`,
        { method: "POST" },
      ),
    onSuccess: (updated, kind) => {
      if (updated.status === "failed") {
        toast.error(
          `Change ${kind} finished with verification errors — previous state was restored automatically.`,
        );
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

  return (
    <div className="max-w-md space-y-2 rounded-md border p-3">
      {showSummary ? (
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={STATUS_VARIANT[change.status]}>
            {change.status.replace("_", " ")}
          </Badge>
          <span className="text-sm font-medium">{change.target_name}</span>
          <span className="text-xs text-muted-foreground">
            {CHANGE_TYPE_LABEL[change.change_type]}
          </span>
        </div>
      ) : null}

      {hasErrors ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive">
          Validation errors — cannot be executed. Open Deployments to review.
        </div>
      ) : null}

      <div className="flex items-center gap-2">
        {change.status === "draft" && !hasErrors ? (
          <Button size="sm" onClick={() => setConfirmKind("execute")}>
            <Rocket className="mr-2 h-3.5 w-3.5" />
            Execute on server
          </Button>
        ) : null}
        {change.status === "executed" ? (
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
              {confirmKind === "execute"
                ? `Execute "${change.target_name}" on the live TM1 server?`
                : `Roll back "${change.target_name}"?`}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {confirmKind === "execute"
                ? "The change is applied to the live server, verified, and automatically restored if verification fails. This action is audited."
                : "The snapshot taken at execution time will be restored on the live server. This action is audited."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => confirmKind && actionMutation.mutate(confirmKind)}
              disabled={actionMutation.isPending}
            >
              {actionMutation.isPending
                ? "Working..."
                : confirmKind === "execute"
                  ? "Execute"
                  : "Roll back"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
