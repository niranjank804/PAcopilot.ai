import { CheckCircle2, Circle, CircleDot, Info, MinusCircle, TriangleAlert, XCircle } from "lucide-react";

import type { ChangeCheck, LifecycleStep } from "@/lib/types";
import { cn } from "@/lib/utils";

const STEP_ICON = {
  done: CheckCircle2,
  current: CircleDot,
  failed: XCircle,
  skipped: MinusCircle,
  pending: Circle,
} as const;

const STEP_TONE = {
  done: "text-success",
  current: "text-primary",
  failed: "text-destructive",
  skipped: "text-muted-foreground",
  pending: "text-muted-foreground/60",
} as const;

const STEP_WORD = {
  done: "done",
  current: "now",
  failed: "failed",
  skipped: "skipped",
  pending: "to do",
} as const;

/**
 * Where a change is in its life — requested, analysed, validated, approved,
 * applied, verified — read from the record, never assumed. Each step's
 * state is written out as well as drawn.
 */
export function ChangeLifecycle({ steps }: { steps: LifecycleStep[] }) {
  if (!steps.length) return null;

  return (
    <ol className="space-y-1.5 text-xs" aria-label="Change lifecycle">
      {steps.map((step) => {
        const Icon = STEP_ICON[step.state];
        return (
          <li key={step.key} className="flex items-start gap-2">
            <Icon className={cn("mt-0.5 size-3.5 shrink-0", STEP_TONE[step.state])} aria-hidden />
            <span className="min-w-0">
              <span className={cn("font-medium", step.state === "pending" && "text-muted-foreground")}>
                {step.label}
              </span>{" "}
              <span className="text-muted-foreground">
                — {STEP_WORD[step.state]}
                {step.at ? ` · ${new Date(step.at).toLocaleString()}` : ""}
              </span>
              {step.detail ? <span className="block text-muted-foreground">{step.detail}</span> : null}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

const CHECK_ICON = { pass: CheckCircle2, warn: TriangleAlert, fail: XCircle, info: Info } as const;
const CHECK_TONE = {
  pass: "text-success",
  warn: "text-warning",
  fail: "text-destructive",
  info: "text-muted-foreground",
} as const;
const CHECK_WORD = { pass: "Passed", warn: "Look at this", fail: "Failed", info: "Note" } as const;

/**
 * The checks a change passed before reaching the approver: static analysis,
 * a compile on the server that saves nothing, code review, impact,
 * parameters. TM1 has no safe trial run for a process, so this list — not a
 * test run — is what stands before approval, and it says so.
 */
export function ChangeChecks({ checks, onlyConcerns = false }: { checks: ChangeCheck[] | null | undefined; onlyConcerns?: boolean }) {
  const shown = (checks ?? []).filter((c) => !onlyConcerns || c.status === "warn" || c.status === "fail");
  if (!shown.length) return null;

  return (
    <ul className="space-y-2 text-xs" aria-label="Pre-deployment checks">
      {shown.map((check) => {
        const Icon = CHECK_ICON[check.status];
        return (
          <li key={check.name} className="flex items-start gap-2">
            <Icon className={cn("mt-0.5 size-3.5 shrink-0", CHECK_TONE[check.status])} aria-hidden />
            <span className="min-w-0">
              <span className="font-medium">{check.name}</span>{" "}
              <span className="text-muted-foreground">
                — {CHECK_WORD[check.status]}: {check.detail}
              </span>
              {check.items?.length ? (
                <ul className="mt-0.5 list-disc pl-4 text-muted-foreground">
                  {check.items.map((item) => (
                    <li key={item} className="break-words">
                      {item}
                    </li>
                  ))}
                </ul>
              ) : null}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
