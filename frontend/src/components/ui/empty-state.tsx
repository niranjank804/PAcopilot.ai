import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** Nothing here yet — said once, the same way, on every surface. */
export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 px-6 py-12 text-center",
        className,
      )}
    >
      {icon ? (
        <span
          className="flex size-10 items-center justify-center rounded-xl bg-muted text-muted-foreground"
          aria-hidden
        >
          {icon}
        </span>
      ) : null}
      <div className="space-y-1">
        <p className="text-[0.9375rem] font-medium text-foreground">{title}</p>
        {description ? (
          <p className="mx-auto max-w-md text-sm text-muted-foreground">
            {description}
          </p>
        ) : null}
      </div>
      {action ? <div className="pt-1">{action}</div> : null}
    </div>
  );
}
