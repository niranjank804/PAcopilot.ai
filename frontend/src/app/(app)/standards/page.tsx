"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  FileSearch,
  Loader2,
  ShieldAlert,
  Upload,
} from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, apiRequest, uploadRequest } from "@/lib/api-client";
import type {
  LearnedStandards,
  LearningRun,
  StandardsReport,
} from "@/lib/types";

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "Something went wrong. Please try again.";
}

/** Confidence is a measured agreement ratio, not a percentage of correctness,
 * so it is labelled by strength rather than shown as a bare number. */
function strength(confidence: number): { label: string; tone: "default" | "secondary" } {
  if (confidence >= 0.8) return { label: "Strong", tone: "default" };
  return { label: "Moderate", tone: "secondary" };
}

function buildFormData(files: FileList): FormData {
  const form = new FormData();

  for (const file of Array.from(files)) {
    form.append("files", file);
  }

  return form;
}

export default function StandardsPage() {
  const queryClient = useQueryClient();
  const learnInput = useRef<HTMLInputElement>(null);
  const previewInput = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [lastRun, setLastRun] = useState<LearningRun | null>(null);

  const standards = useQuery({
    queryKey: ["learning", "standards"],
    queryFn: () => apiRequest<LearnedStandards>("/learning/standards"),
  });

  const learn = useMutation({
    mutationFn: (files: FileList) =>
      uploadRequest<LearningRun>("/learning/corpus", buildFormData(files)),
    onSuccess: (run) => {
      setLastRun(run);
      queryClient.invalidateQueries({ queryKey: ["learning", "standards"] });

      if (!run.replaced_existing) {
        toast.warning("Your existing standards were kept.");
        return;
      }

      toast.success(
        `Learned ${run.conventions_learned} standard(s) from ${run.processes_parsed} processes.`,
      );
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const previewReport = useMutation({
    mutationFn: (files: FileList) =>
      uploadRequest<StandardsReport>("/learning/report", buildFormData(files)),
    onSuccess: (report) => setPreview(report.markdown),
    onError: (error) => toast.error(errorMessage(error)),
  });

  const conventions = standards.data?.conventions ?? [];
  const busy = learn.isPending || previewReport.isPending;

  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Coding Standards</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Upload your exported TurboIntegrator processes and PA-Copilot measures
          how your team actually writes TM1. Generated code follows what it
          finds, and cites the evidence.
        </p>
      </div>

      <input
        ref={learnInput}
        type="file"
        multiple
        accept=".pro,.txt,.zip"
        className="hidden"
        onChange={(event) => {
          if (event.target.files?.length) learn.mutate(event.target.files);
          event.target.value = "";
        }}
      />
      <input
        ref={previewInput}
        type="file"
        multiple
        accept=".pro,.txt,.zip"
        className="hidden"
        onChange={(event) => {
          if (event.target.files?.length) previewReport.mutate(event.target.files);
          event.target.value = "";
        }}
      />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Analyse a corpus</CardTitle>
          <CardDescription>
            A zip of your TM1 process exports, or individual .pro files. Around
            eight processes are needed before a shared practice counts as a
            standard.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => previewInput.current?.click()} disabled={busy} variant="outline">
              {previewReport.isPending ? (
                <Loader2 className="mr-2 size-4 animate-spin" />
              ) : (
                <FileSearch className="mr-2 size-4" />
              )}
              Preview report
            </Button>
            <Button onClick={() => learnInput.current?.click()} disabled={busy}>
              {learn.isPending ? (
                <Loader2 className="mr-2 size-4 animate-spin" />
              ) : (
                <Upload className="mr-2 size-4" />
              )}
              Set as our standards
            </Button>
          </div>
          <p className="text-muted-foreground text-xs">
            Preview shows what would be learned without changing anything.
          </p>

          {lastRun && (
            <div className="flex flex-col gap-2 border-t pt-4 text-sm">
              <div className="flex flex-wrap gap-x-6 gap-y-1">
                <span>
                  <strong>{lastRun.processes_parsed}</strong> processes read
                </span>
                {lastRun.processes_failed > 0 && (
                  <span className="text-destructive">
                    <strong>{lastRun.processes_failed}</strong> could not be read
                  </span>
                )}
                <span>
                  <strong>{lastRun.conventions_learned}</strong> standards
                </span>
              </div>

              {lastRun.note && (
                <div className="flex gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-3">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600" />
                  <p className="text-xs">{lastRun.note}</p>
                </div>
              )}

              {lastRun.files_with_stored_credentials > 0 && (
                <div className="flex gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-3">
                  <ShieldAlert className="mt-0.5 size-4 shrink-0 text-destructive" />
                  <p className="text-xs">
                    <strong>{lastRun.files_with_stored_credentials}</strong> of the
                    uploaded exports contain a saved datasource username or
                    password. Those values were never read or stored, but treat
                    the export files themselves as secret — don&apos;t attach them
                    to tickets or email.
                  </p>
                </div>
              )}

              {lastRun.patterns.length > 0 && (
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {lastRun.patterns.map((pattern) => (
                    <Badge key={pattern.key} variant="secondary" title={pattern.description}>
                      {pattern.name} · {pattern.process_count}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Your standards</CardTitle>
          <CardDescription>
            What the code-writing agents are held to, and the evidence for each.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {standards.isLoading ? (
            <div className="flex flex-col gap-3">
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-14 w-full" />
            </div>
          ) : conventions.length === 0 ? (
            <p className="text-muted-foreground py-6 text-center text-sm">
              Nothing learned yet. Until a corpus is analysed, generated code
              follows documented IBM practice and says so.
            </p>
          ) : (
            <ul className="flex flex-col gap-3">
              {conventions.map((convention) => {
                const tone = strength(convention.confidence);

                return (
                  <li
                    key={convention.key}
                    className="flex flex-col gap-1.5 rounded-md border p-3"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <p className="text-sm font-medium">{convention.statement}</p>
                      <Badge variant={tone.tone} className="shrink-0">
                        {tone.label}
                      </Badge>
                    </div>
                    <p className="text-muted-foreground text-xs tabular-nums">
                      Followed by {convention.support} of {convention.sample}{" "}
                      processes
                    </p>
                    {convention.counter_examples.length > 0 && (
                      <p className="text-muted-foreground text-xs">
                        Exceptions: {convention.counter_examples.slice(0, 3).join(", ")}
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      {preview && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Report preview</CardTitle>
            <CardDescription>
              Nothing was saved. Review what your codebase does — and does not —
              do before making it the standard.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <pre className="bg-muted max-h-[32rem] overflow-auto rounded-md p-4 text-xs whitespace-pre-wrap">
              {preview}
            </pre>
            <Button
              variant="ghost"
              size="sm"
              className="mt-3"
              onClick={() => setPreview(null)}
            >
              Dismiss
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
