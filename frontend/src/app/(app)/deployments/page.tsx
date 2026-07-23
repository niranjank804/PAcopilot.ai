"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquare, Plus, ShieldCheck } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ChangeActionCard } from "@/components/change-action-card";
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
import { CHANGE_TYPE_LABEL, PROCESS_FIELD_MAP, STATUS_VARIANT } from "@/lib/change-format";
import { cn } from "@/lib/utils";
import type {
  RelatedObject,
  TM1ChangeDetail,
  TM1ChangeSummary,
  TM1Connection,
} from "@/lib/types";

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong.";
}

function isNote(item: RelatedObject | { note: string }): item is { note: string } {
  return "note" in item;
}

function DiffBlock({ label, before, after }: { label: string; before: string; after: string }) {
  if (before === after) {
    return null;
  }

  return (
    <div className="space-y-1">
      <p className="text-xs font-medium text-muted-foreground capitalize">{label}</p>
      <div className="grid gap-2 sm:grid-cols-2">
        <div>
          <p className="mb-1 text-xs text-muted-foreground">Current</p>
          <pre className="max-h-56 overflow-auto rounded-md bg-destructive/10 p-2 text-xs whitespace-pre-wrap">
            {before || "(empty)"}
          </pre>
        </div>
        <div>
          <p className="mb-1 text-xs text-muted-foreground">Proposed</p>
          <pre className="max-h-56 overflow-auto rounded-md bg-primary/10 p-2 text-xs whitespace-pre-wrap">
            {after || "(empty)"}
          </pre>
        </div>
      </div>
    </div>
  );
}

function ChangeDiff({ detail }: { detail: TM1ChangeDetail }) {
  const { change, preview } = detail;

  if (change.change_type === "update_rules") {
    return (
      <DiffBlock
        label="rules"
        before={String(preview.current?.rules ?? "")}
        after={String(preview.proposed?.rules ?? "")}
      />
    );
  }

  if (change.change_type === "delete_process") {
    return (
      <p className="text-sm text-muted-foreground">
        This process will be deleted when executed.
      </p>
    );
  }

  const currentProcess = preview.current?.process as Record<string, string> | undefined;
  const proposedFields = (change.new_content ?? {}) as Record<string, string>;

  return (
    <div className="space-y-3">
      {Object.entries(PROCESS_FIELD_MAP).map(([shortKey, longKey]) => {
        if (!(shortKey in proposedFields)) return null;

        return (
          <DiffBlock
            key={shortKey}
            label={shortKey}
            before={currentProcess?.[longKey] ?? ""}
            after={String(proposedFields[shortKey] ?? "")}
          />
        );
      })}
    </div>
  );
}

const changeSchema = z
  .object({
    change_type: z.enum([
      "update_rules",
      "create_process",
      "update_process",
      "delete_process",
    ]),
    target_name: z.string().min(1, "Required"),
    rules: z.string().optional(),
    prolog: z.string().optional(),
    metadata: z.string().optional(),
    data: z.string().optional(),
    epilog: z.string().optional(),
  })
  .refine(
    (values) => values.change_type !== "update_rules" || !!values.rules?.trim(),
    { message: "Rule text is required", path: ["rules"] },
  );

type ChangeFormValues = z.infer<typeof changeSchema>;

export default function DeploymentsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const [connectionId, setConnectionId] = useState<string | null>(
    () => searchParams.get("connection"),
  );
  const [selectedChangeId, setSelectedChangeId] = useState<string | null>(
    () => searchParams.get("change"),
  );
  const [createOpen, setCreateOpen] = useState(false);

  const connectionsQuery = useQuery({
    queryKey: ["tm1-connections"],
    queryFn: () => apiRequest<TM1Connection[]>("/tm1/connections"),
  });

  const activeConnectionId =
    connectionId ?? connectionsQuery.data?.[0]?.id ?? null;

  const changesQuery = useQuery({
    queryKey: ["tm1-changes", activeConnectionId],
    queryFn: () =>
      apiRequest<TM1ChangeSummary[]>(
        `/tm1/connections/${activeConnectionId}/changes`,
      ),
    enabled: activeConnectionId !== null,
  });

  const detailQuery = useQuery({
    queryKey: ["tm1-change-detail", activeConnectionId, selectedChangeId],
    queryFn: () =>
      apiRequest<TM1ChangeDetail>(
        `/tm1/connections/${activeConnectionId}/changes/${selectedChangeId}`,
      ),
    enabled: activeConnectionId !== null && selectedChangeId !== null,
  });

  const {
    register,
    handleSubmit,
    watch,
    reset,
    control,
    formState: { errors },
  } = useForm<ChangeFormValues>({
    resolver: zodResolver(changeSchema),
    defaultValues: { change_type: "update_rules" },
  });

  const changeType = watch("change_type");

  const createMutation = useMutation({
    mutationFn: (values: ChangeFormValues) => {
      let new_content: Record<string, string> | null = null;

      if (values.change_type === "update_rules") {
        new_content = { rules: values.rules ?? "" };
      } else if (
        values.change_type === "create_process" ||
        values.change_type === "update_process"
      ) {
        new_content = {};
        for (const key of ["prolog", "metadata", "data", "epilog"] as const) {
          if (values[key]?.trim()) {
            new_content[key] = values[key] as string;
          }
        }
      }

      return apiRequest<TM1ChangeSummary>(
        `/tm1/connections/${activeConnectionId}/changes`,
        {
          method: "POST",
          body: {
            change_type: values.change_type,
            target_name: values.target_name,
            new_content,
          },
        },
      );
    },
    onSuccess: (change) => {
      toast.success(`Draft change created for "${change.target_name}".`);
      setCreateOpen(false);
      reset({ change_type: "update_rules" });
      queryClient.invalidateQueries({ queryKey: ["tm1-changes", activeConnectionId] });
      setSelectedChangeId(change.id);
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const selectedDetail = detailQuery.data;

  const discussInChat = () => {
    if (!selectedDetail) return;

    const { change } = selectedDetail;
    const prompt =
      `Explain the impact and risk of this draft change: ${CHANGE_TYPE_LABEL[change.change_type].toLowerCase()} ` +
      `on "${change.target_name}" in TM1 connection ${activeConnectionId}. ` +
      `Look up its current state and dependencies before answering, and suggest whether it's safe to deploy.`;

    router.push(`/chat?prompt=${encodeURIComponent(prompt)}`);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Deployments</h1>
          <p className="text-sm text-muted-foreground">
            Review, execute, and roll back proposed TM1 changes. Executing a
            change writes to the live server.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {activeConnectionId ? (
            <Select
              value={activeConnectionId}
              onValueChange={(value) => {
                setConnectionId(value);
                setSelectedChangeId(null);
              }}
            >
              <SelectTrigger className="w-64" aria-label="Connection">
                <SelectValue placeholder="Select connection">
                  {(value: string) =>
                    connectionsQuery.data?.find((c) => c.id === value)?.name ??
                    "Select connection"
                  }
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {connectionsQuery.data?.map((connection) => (
                  <SelectItem key={connection.id} value={connection.id}>
                    {connection.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <Skeleton className="h-9 w-64" />
          )}
          <Button
            size="sm"
            disabled={!activeConnectionId}
            onClick={() => setCreateOpen(true)}
          >
            <Plus className="mr-2 h-4 w-4" />
            New Change
          </Button>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Change log</CardTitle>
            <CardDescription>
              Drafts wait for human review; every execute and rollback is
              audited.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {changesQuery.isError ? (
              <p className="py-6 text-center text-sm text-destructive">
                Failed to load: {errorMessage(changesQuery.error)}
              </p>
            ) : changesQuery.isPending && activeConnectionId ? (
              <div className="space-y-2">
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            ) : !changesQuery.data?.length ? (
              <p className="py-10 text-center text-sm text-muted-foreground">
                No changes for this connection yet — drafts created by the AI
                agents or via &quot;New Change&quot; will appear here.
              </p>
            ) : (
              <ul className="divide-y">
                {changesQuery.data.map((change) => (
                  <li key={change.id}>
                    <button
                      onClick={() => setSelectedChangeId(change.id)}
                      className={cn(
                        "flex w-full items-center justify-between gap-2 px-2 py-3 text-left text-sm hover:bg-accent",
                        selectedChangeId === change.id && "bg-accent",
                      )}
                    >
                      <span>
                        <span className="font-medium">{change.target_name}</span>
                        <span className="ml-2 text-xs text-muted-foreground">
                          {CHANGE_TYPE_LABEL[change.change_type]}
                        </span>
                      </span>
                      <span className="flex items-center gap-2">
                        <span className="text-xs text-muted-foreground">
                          {new Date(change.created_at).toLocaleString()}
                        </span>
                        <Badge variant={STATUS_VARIANT[change.status]}>
                          {change.status.replace("_", " ")}
                        </Badge>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Review</CardTitle>
            <CardDescription>
              Current vs. proposed content, impact, and deploy actions.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {!selectedChangeId ? (
              <p className="py-10 text-center text-sm text-muted-foreground">
                Select a change to review it.
              </p>
            ) : detailQuery.isError ? (
              <p className="py-6 text-center text-sm text-destructive">
                Failed to load: {errorMessage(detailQuery.error)}
              </p>
            ) : detailQuery.isPending || !selectedDetail ? (
              <div className="space-y-2">
                <Skeleton className="h-24 w-full" />
                <Skeleton className="h-24 w-full" />
              </div>
            ) : (
              <>
                <div className="flex items-center gap-2">
                  <Badge variant={STATUS_VARIANT[selectedDetail.change.status]}>
                    {selectedDetail.change.status.replace("_", " ")}
                  </Badge>
                  <span className="text-sm font-medium">
                    {selectedDetail.change.target_name}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {CHANGE_TYPE_LABEL[selectedDetail.change.change_type]}
                  </span>
                </div>

                {selectedDetail.change.error_message ? (
                  <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
                    {selectedDetail.change.error_message}
                  </div>
                ) : null}

                {selectedDetail.change.validation_errors?.length ? (
                  <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm">
                    <p className="font-medium text-destructive">
                      Validation errors — cannot be executed
                    </p>
                    <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-destructive">
                      {selectedDetail.change.validation_errors.map((err, index) => (
                        <li key={index}>
                          {err.Procedure} line {err.LineNumber}: {err.Message}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                <ChangeDiff detail={selectedDetail} />

                <div>
                  <p className="mb-1 text-xs font-medium text-muted-foreground">
                    Impact ({selectedDetail.change.impact?.length ?? 0}{" "}
                    downstream objects)
                  </p>
                  <div className="max-h-40 overflow-auto rounded-md border p-2 text-xs">
                    {selectedDetail.change.impact?.length ? (
                      selectedDetail.change.impact.map((entry, index) => (
                        <div key={index} className="py-0.5">
                          {isNote(entry)
                            ? entry.note
                            : `${entry.object_type} ${entry.name} (${entry.relationship_type})`}
                        </div>
                      ))
                    ) : (
                      <span className="text-muted-foreground">
                        No impact recorded.
                      </span>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <Button variant="outline" size="sm" onClick={discussInChat}>
                    <MessageSquare className="mr-2 h-4 w-4" />
                    Discuss in AI Chat
                  </Button>
                  <span className="flex items-center gap-1 text-xs text-muted-foreground">
                    <ShieldCheck className="h-3.5 w-3.5" />
                    Requires deploy permission; fully audited.
                  </span>
                </div>

                {activeConnectionId ? (
                  <ChangeActionCard
                    connectionId={activeConnectionId}
                    changeId={selectedDetail.change.id}
                    showSummary={false}
                  />
                ) : null}
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>New Change</DialogTitle>
            <DialogDescription>
              Creates a draft — nothing is applied to the TM1 server until you
              review and execute it.
            </DialogDescription>
          </DialogHeader>
          <form
            onSubmit={handleSubmit((values) => createMutation.mutate(values))}
            className="space-y-4"
          >
            <div className="space-y-2">
              <Label htmlFor="change_type">Change type</Label>
              <Controller
                control={control}
                name="change_type"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger id="change_type" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="update_rules">Update rules</SelectItem>
                      <SelectItem value="create_process">Create process</SelectItem>
                      <SelectItem value="update_process">Update process</SelectItem>
                      <SelectItem value="delete_process">Delete process</SelectItem>
                    </SelectContent>
                  </Select>
                )}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="target_name">
                {changeType === "update_rules" ? "Cube name" : "Process name"}
              </Label>
              <Input id="target_name" {...register("target_name")} />
              {errors.target_name ? (
                <p className="text-sm text-destructive">
                  {errors.target_name.message}
                </p>
              ) : null}
            </div>

            {changeType === "update_rules" ? (
              <div className="space-y-2">
                <Label htmlFor="rules">Proposed rule text</Label>
                <Textarea
                  id="rules"
                  rows={8}
                  className="font-mono text-xs"
                  {...register("rules")}
                />
                {errors.rules ? (
                  <p className="text-sm text-destructive">{errors.rules.message}</p>
                ) : null}
              </div>
            ) : null}

            {changeType === "create_process" || changeType === "update_process" ? (
              <>
                <p className="text-xs text-muted-foreground">
                  Leave a field blank to leave that section unchanged (update
                  only) or empty (create).
                </p>
                {(["prolog", "metadata", "data", "epilog"] as const).map((field) => (
                  <div key={field} className="space-y-2">
                    <Label htmlFor={field} className="capitalize">
                      {field}
                    </Label>
                    <Textarea
                      id={field}
                      rows={4}
                      className="font-mono text-xs"
                      {...register(field)}
                    />
                  </div>
                ))}
              </>
            ) : null}

            {changeType === "delete_process" ? (
              <p className="text-sm text-muted-foreground">
                This will delete the named process when executed. No content
                needed.
              </p>
            ) : null}

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setCreateOpen(false)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={createMutation.isPending}>
                {createMutation.isPending ? "Creating..." : "Create draft"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
