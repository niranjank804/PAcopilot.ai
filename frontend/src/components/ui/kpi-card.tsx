import { Info } from "lucide-react";
import type { ReactNode } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { Tip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/**
 * A single measured number.
 *
 * Loading and failure are part of the component rather than each page's
 * own conditional, because the mistake those conditionals kept making was
 * rendering 0 while a request was still in flight — a zero that looks
 * like a measurement.
 */
export function KpiCard({
  label,
  value,
  hint,
  isPending,
  isError,
  errorText = "Unavailable",
  icon,
  help,
  className,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  isPending?: boolean;
  isError?: boolean;
  errorText?: string;
  icon?: ReactNode;
  /** How this number is computed and what to do about it. A focusable
   * info button, so it reaches keyboard users as well as the cursor. */
  help?: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-border bg-card p-6 shadow-card",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <p className="flex items-center gap-1.5 text-[0.8125rem] font-medium text-muted-foreground">
          {label}
          {help ? (
            <Tip content={help}>
              <button
                type="button"
                aria-label={`About ${label}`}
                className="rounded-full text-tertiary-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <Info className="size-3.5" aria-hidden />
              </button>
            </Tip>
          ) : null}
        </p>
        {icon ? (
          <span className="text-tertiary-foreground" aria-hidden>
            {icon}
          </span>
        ) : null}
      </div>

      <div className="mt-3 tabular-nums">
        {isPending ? (
          <Skeleton className="h-9 w-24" />
        ) : isError ? (
          <p className="text-section font-semibold text-muted-foreground">—</p>
        ) : (
          <p className="text-kpi">{value}</p>
        )}
      </div>

      <p
        className={cn(
          "mt-2 text-[0.8125rem] leading-5",
          isError ? "text-destructive" : "text-tertiary-foreground",
        )}
      >
        {isPending ? <Skeleton className="h-4 w-28" /> : isError ? errorText : hint}
      </p>
    </div>
  );
}
