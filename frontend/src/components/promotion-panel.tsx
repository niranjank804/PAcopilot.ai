"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Download, FileText } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ChangeChecks } from "@/components/change-lifecycle";
import { EnvironmentBadge } from "@/components/environment-badge";
import { ImpactSummary, type ImpactEntry } from "@/components/impact-summary";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, apiRequest } from "@/lib/api-client";
import type { ChangeCheck, Environment, TM1ChangeSummary, TM1Connection } from "@/lib/types";

// Mirrors NEXT_ENVIRONMENT in backend/src/tm1/deployment/promotion.py.
const NEXT: Partial<Record<Environment, Environment>> = { dev: "qa", qa: "prod" };

interface PackageStage {
  change_id: string;
  environment: string;
  connection: string;
  status: string;
  requested_by: string | null;
  requested_at: string;
  approved_by: string | null;
  approved_at: string | null;
  verified: boolean;
  same_content: boolean;
}

interface DeploymentPackage {
  manifest: {
    change_type: string;
    object: string;
    target_connection: string;
    target_environment: string;
    content_sha256: string;
  };
  stages: PackageStage[];
  evidence: {
    verified_in: string[];
    content_unchanged_since_first_stage: boolean;
    checks_here: ChangeCheck[];
  };
  impact: ImpactEntry[];
  approval_rule: string;
  rollback_plan: string;
}

function message(error: unknown) {
  return error instanceof ApiError ? error.message : "Something went wrong.";
}

/**
 * Promote an applied change to the next environment, and read the package
 * that goes with any change: where it has been, who approved it, what was
 * verified, and how to undo it.
 */
export function PromotionPanel({
  change,
  connections,
  environment,
  onPromoted,
}: {
  change: TM1ChangeSummary;
  connections: TM1Connection[];
  environment: Environment;
  onPromoted: (connectionId: string, changeId: string) => void;
}) {
  const queryClient = useQueryClient();
  const [packageOpen, setPackageOpen] = useState(false);
  const next = NEXT[environment];
  const targets = connections.filter((c) => (c.environment ?? "dev") === next);
  const [target, setTarget] = useState<string | null>(null);
  const chosen = target ?? targets[0]?.id ?? null;

  const promotable =
    change.status === "executed" &&
    !change.rolled_back_at &&
    change.change_type !== "run_process" &&
    Boolean(next);

  const promote = useMutation({
    mutationFn: () =>
      apiRequest<TM1ChangeSummary>(
        `/tm1/connections/${change.connection_id}/changes/${change.id}/promote`,
        { method: "POST", body: { target_connection_id: chosen } },
      ),
    onSuccess: (draft) => {
      toast.success(
        `Drafted on ${next?.toUpperCase()}. It is checked against that server and needs approval there.`,
      );
      queryClient.invalidateQueries({ queryKey: ["tm1-changes"] });
      onPromoted(draft.connection_id, draft.id);
    },
    onError: (error) => toast.error(message(error)),
  });

  const pkg = useQuery({
    queryKey: ["tm1-change-package", change.id],
    queryFn: () =>
      apiRequest<DeploymentPackage>(
        `/tm1/connections/${change.connection_id}/changes/${change.id}/package`,
      ),
    enabled: packageOpen,
  });

  const download = () => {
    if (!pkg.data) return;
    const blob = new Blob([JSON.stringify(pkg.data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `deployment-package-${pkg.data.manifest.object}-${change.id.slice(0, 8)}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex flex-wrap items-center gap-2" data-tour="governance-promotion">
      {promotable ? (
        targets.length ? (
          <>
            {targets.length > 1 ? (
              <Select value={chosen} onValueChange={(value) => value && setTarget(value)}>
                <SelectTrigger className="w-48" aria-label={`${next?.toUpperCase()} connection`}>
                  <SelectValue>
                    {(value: string) => targets.find((t) => t.id === value)?.name ?? "Connection"}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {targets.map((t) => (
                    <SelectItem key={t.id} value={t.id}>
                      {t.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : null}
            <Button size="sm" onClick={() => promote.mutate()} disabled={promote.isPending || !chosen}>
              <ArrowUpRight className="mr-2 h-3.5 w-3.5" />
              Promote to {next?.toUpperCase()}
              {targets.length === 1 ? ` (${targets[0].name})` : ""}
            </Button>
          </>
        ) : (
          <span className="text-xs text-muted-foreground">
            No {next?.toUpperCase()} connection to promote to — set one&apos;s Environment on Connections.
          </span>
        )
      ) : null}

      <Button size="sm" variant="outline" onClick={() => setPackageOpen(true)}>
        <FileText className="mr-2 h-3.5 w-3.5" />
        Deployment package
      </Button>

      <Dialog open={packageOpen} onOpenChange={setPackageOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Deployment package</DialogTitle>
            <DialogDescription>
              Where this change has been, who approved it, what was verified, and how to undo it.
            </DialogDescription>
          </DialogHeader>
          {pkg.isPending ? (
            <Skeleton className="h-40 w-full" />
          ) : pkg.isError ? (
            <p className="text-sm text-destructive">{message(pkg.error)}</p>
          ) : (
            <div className="space-y-4 text-sm">
              <p>
                <span className="font-medium">{pkg.data.manifest.change_type.replaceAll("_", " ")}</span>{" "}
                <span className="font-medium">{pkg.data.manifest.object}</span> on{" "}
                {pkg.data.manifest.target_connection}{" "}
                <EnvironmentBadge environment={pkg.data.manifest.target_environment.toLowerCase() as Environment} />
              </p>

              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">Road so far</p>
                <ol className="space-y-1 text-xs">
                  {pkg.data.stages.map((stage) => (
                    <li key={stage.change_id}>
                      <span className="font-medium">{stage.environment}</span> ({stage.connection}) —{" "}
                      {stage.status}
                      {stage.verified ? ", verified" : ""}; requested by {stage.requested_by ?? "unknown"}
                      {stage.approved_by
                        ? `, approved by ${stage.approved_by} ${new Date(stage.approved_at as string).toLocaleString()}`
                        : ", not approved yet"}
                      {stage.same_content ? "" : " — content differs from the first stage"}
                    </li>
                  ))}
                </ol>
                <p className="mt-1 text-xs text-muted-foreground">
                  {pkg.data.evidence.verified_in.length
                    ? `Verified in ${pkg.data.evidence.verified_in.join(" and ")}. `
                    : "Not verified in a lower environment. "}
                  {pkg.data.evidence.content_unchanged_since_first_stage
                    ? "The content is identical at every stage."
                    : "The content changed between stages."}
                </p>
              </div>

              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">Checks on this server</p>
                <ChangeChecks checks={pkg.data.evidence.checks_here} />
              </div>

              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">Impact here</p>
                <ImpactSummary entries={pkg.data.impact} maxItems={10} />
              </div>

              <div className="space-y-1 text-xs">
                <p>
                  <span className="font-medium">Approval: </span>
                  {pkg.data.approval_rule}
                </p>
                <p>
                  <span className="font-medium">Rollback plan: </span>
                  {pkg.data.rollback_plan}
                </p>
              </div>

              <Button size="sm" variant="outline" onClick={download}>
                <Download className="mr-2 h-3.5 w-3.5" />
                Download package (JSON)
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
