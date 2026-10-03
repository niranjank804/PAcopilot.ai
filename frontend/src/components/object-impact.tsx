"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { ImpactSummary, type ImpactEntry } from "@/components/impact-summary";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, apiRequest } from "@/lib/api-client";
import { cn } from "@/lib/utils";

interface ImpactResult {
  in_graph: boolean;
  items: ImpactEntry[];
  not_covered: string[];
  graph: { extracted_at: string | null; note?: string };
}

/**
 * "What breaks if I change or delete this?" for one object, before anyone
 * drafts the change: every object it reaches, ranked, and what the
 * dependency map cannot see.
 */
export function ObjectImpact({
  connectionId,
  objectType,
  name,
}: {
  connectionId: string;
  objectType: string;
  name: string;
}) {
  const [changeKind, setChangeKind] = useState<"modify" | "delete">("modify");

  const impact = useQuery({
    queryKey: ["tm1-impact", connectionId, objectType, name, changeKind],
    queryFn: () =>
      apiRequest<ImpactResult>(
        `/tm1/connections/${connectionId}/metadata/impact?` +
          new URLSearchParams({ object_type: objectType, name, change_kind: changeKind }),
      ),
  });

  return (
    <div className="space-y-3">
      <div role="group" aria-label="Kind of change" className="flex w-fit rounded-lg border p-0.5 text-sm">
        {(["modify", "delete"] as const).map((kind) => (
          <button
            key={kind}
            type="button"
            aria-pressed={changeKind === kind}
            onClick={() => setChangeKind(kind)}
            className={cn(
              "rounded-md px-3 py-1",
              changeKind === kind ? "bg-secondary font-medium" : "text-muted-foreground",
            )}
          >
            {kind === "modify" ? "If changed" : "If deleted"}
          </button>
        ))}
      </div>

      {impact.isPending ? (
        <Skeleton className="h-24 w-full" />
      ) : impact.isError ? (
        <p className="text-sm text-destructive">
          {impact.error instanceof ApiError ? impact.error.message : "Could not analyse the impact."}
        </p>
      ) : (
        <>
          <ImpactSummary
            entries={impact.data.in_graph ? impact.data.items : [{ note: impact.data.not_covered[0] }]}
          />
          {impact.data.graph.note ? (
            <p className="text-xs text-warning">{impact.data.graph.note}</p>
          ) : null}
          <div className="text-xs text-muted-foreground">
            <p className="font-medium">Not covered by the dependency map</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-4">
              {(impact.data.in_graph ? impact.data.not_covered : impact.data.not_covered.slice(1)).map(
                (item) => (
                  <li key={item}>{item}</li>
                ),
              )}
            </ul>
          </div>
        </>
      )}
    </div>
  );
}
