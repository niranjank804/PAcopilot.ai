import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * The top of every page: one title, one line of context, actions right.
 *
 * Each screen previously wrote its own heading block, and they had drifted
 * two type steps apart. Routing them through one component is what makes
 * the type scale in globals.css actually hold.
 */
export function PageHeader({
  title,
  description,
  actions,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between",
        className,
      )}
    >
      <div className="min-w-0 space-y-1.5">
        <h1 className="page-title">{title}</h1>
        {description ? <p className="page-subtitle">{description}</p> : null}
      </div>
      {actions ? (
        <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
      ) : null}
    </div>
  );
}
