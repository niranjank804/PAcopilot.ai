import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";

import type { TM1ChangeSummary } from "@/lib/types";

/** One line of a run draft's plan, as the backend's `run_plan` writes it. */
interface PlanEntry {
  kind: "parameter" | "writes_cube" | "calls_process" | "note";
  name?: string;
  value?: unknown;
  source?: string;
  note?: string;
}

interface ExecutionResult {
  success?: boolean;
  status?: string;
  error_log_file?: string | null;
  error_log_excerpt?: string | null;
  duration_ms?: number;
  error_locations?: { section: string; line_number: number; message: string }[];
}

function plan(change: TM1ChangeSummary): PlanEntry[] {
  return ((change.impact ?? []) as unknown as PlanEntry[]).filter(
    (entry) => entry && typeof entry === "object" && "kind" in entry,
  );
}

function display(value: unknown): string {
  if (value === null || value === undefined || value === "") return "(empty)";
  return String(value);
}

/**
 * What a process run will do, shown before anyone approves it, and what TM1
 * said after it ran.
 *
 * Every parameter is listed with the value the run will actually take —
 * including the defaults nobody typed — because an approver who sees only
 * the values the assistant chose cannot tell what the process will do with
 * the rest. The cubes it writes come from parsing its code, and are labelled
 * as such.
 */
export function RunPlan({ change }: { change: TM1ChangeSummary }) {
  const entries = plan(change);
  const parameters = entries.filter((e) => e.kind === "parameter");
  const writes = entries.filter((e) => e.kind === "writes_cube");
  const calls = entries.filter((e) => e.kind === "calls_process");
  const notes = entries.filter((e) => e.kind === "note");
  const result = change.execution_result as ExecutionResult | null | undefined;

  return (
    <div className="space-y-3 text-sm" data-tour="governance-run-plan">
      <div>
        <p className="text-xs font-medium text-muted-foreground">Parameters</p>
        {parameters.length ? (
          <table className="mt-1 w-full text-xs">
            <tbody>
              {parameters.map((p) => (
                <tr key={p.name} className="border-b last:border-0">
                  <td className="py-1 pr-3 font-mono">{p.name}</td>
                  <td className="py-1 pr-3 font-mono break-all">{display(p.value)}</td>
                  <td className="py-1 text-muted-foreground">
                    {p.source === "default" ? "default" : "given"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="mt-1 text-xs text-muted-foreground">This process takes no parameters.</p>
        )}
      </div>

      {writes.length ? (
        <div>
          <p className="text-xs font-medium text-muted-foreground">
            Writes to (from its code)
          </p>
          <p className="mt-1 text-xs">{writes.map((w) => w.name).join(", ")}</p>
        </div>
      ) : null}

      {calls.length ? (
        <div>
          <p className="text-xs font-medium text-muted-foreground">Calls</p>
          <p className="mt-1 text-xs">{calls.map((c) => c.name).join(", ")}</p>
        </div>
      ) : null}

      {notes.map((n, index) => (
        <p key={index} className="flex gap-1.5 text-xs text-muted-foreground">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
          {n.note}
        </p>
      ))}

      {result ? (
        <div
          className={
            result.success
              ? "rounded-md border border-primary/30 bg-primary/5 p-2"
              : "rounded-md border border-destructive/40 bg-destructive/5 p-2"
          }
        >
          <p className="flex items-center gap-1.5 text-xs font-medium">
            {result.success ? (
              <CheckCircle2 className="h-3.5 w-3.5 text-primary" />
            ) : (
              <XCircle className="h-3.5 w-3.5 text-destructive" />
            )}
            Verified from TM1: {result.status ?? "no status"}
            {typeof result.duration_ms === "number"
              ? ` · ${(result.duration_ms / 1000).toFixed(1)} s`
              : ""}
          </p>
          {result.error_log_file ? (
            <p className="mt-1 text-xs text-muted-foreground">
              Error log: <span className="font-mono">{result.error_log_file}</span>
            </p>
          ) : null}
          {result.error_locations?.length ? (
            <ul className="mt-1 list-disc pl-4 text-xs">
              {result.error_locations.slice(0, 5).map((location, index) => (
                <li key={index}>
                  {location.section} line {location.line_number}: {location.message}
                </li>
              ))}
            </ul>
          ) : null}
          {result.error_log_excerpt ? (
            <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded bg-background p-2 text-[11px]">
              {result.error_log_excerpt}
            </pre>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
