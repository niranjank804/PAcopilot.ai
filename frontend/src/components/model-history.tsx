"use client";

import { useQuery } from "@tanstack/react-query";
import { History, Loader2, RefreshCw } from "lucide-react";

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
import { apiRequest } from "@/lib/api-client";

interface NamedObject {
  type: string;
  name: string;
}

interface Edge {
  from: string;
  relationship: string;
  to: string;
}

export interface ExtractionRecord {
  id: string;
  trigger: "manual" | "schedule";
  status: "succeeded" | "failed";
  started_at: string;
  object_count: number;
  relationship_count: number;
  unresolved_references: number;
  error_message: string | null;
  changes: {
    first: boolean;
    counts: {
      objects_added: number;
      objects_removed: number;
      relationships_added: number;
      relationships_removed: number;
    };
    objects_added: NamedObject[];
    objects_removed: NamedObject[];
    relationships_added: Edge[];
    relationships_removed: Edge[];
  } | null;
}

// Mirrors STALE_AFTER_DAYS in backend/src/tm1/metadata/history.py.
const STALE_AFTER_DAYS = 7;

function ago(iso: string): string {
  const days = (Date.now() - new Date(iso).getTime()) / 86_400_000;
  if (days < 1 / 24) return "just now";
  if (days < 1) return `${Math.round(days * 24)} h ago`;
  return `${Math.round(days)} day${Math.round(days) === 1 ? "" : "s"} ago`;
}

function edgeText(edge: Edge): string {
  return `${edge.from.split(":").slice(1).join(":")} ${edge.relationship.replaceAll("_", " ")} ${edge.to.split(":").slice(1).join(":")}`;
}

function ChangeList({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground">{title}</p>
      <ul className="mt-1 space-y-0.5 text-xs">
        {items.slice(0, 12).map((item) => (
          <li key={item} className="truncate">
            {item}
          </li>
        ))}
        {items.length > 12 ? (
          <li className="text-muted-foreground">and {items.length - 12} more</li>
        ) : null}
      </ul>
    </div>
  );
}

/**
 * When the dependency map was last read from TM1, and what changed in the
 * model between reads. The map answers every "what depends on…" question,
 * so how old it is matters as much as what it says.
 */
export function ModelHistory({
  connectionId,
  onExtract,
  extracting,
}: {
  connectionId: string;
  onExtract: () => void;
  extracting: boolean;
}) {
  const history = useQuery({
    queryKey: ["tm1-extractions", connectionId],
    queryFn: () =>
      apiRequest<ExtractionRecord[]>(`/tm1/connections/${connectionId}/metadata/history?limit=10`),
  });

  const latest = history.data?.find((r) => r.status === "succeeded");
  const stale =
    latest && (Date.now() - new Date(latest.started_at).getTime()) / 86_400_000 > STALE_AFTER_DAYS;

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
        <div className="space-y-1">
          <CardTitle className="flex items-center gap-2 text-base">
            <History className="size-4" aria-hidden />
            Model map
          </CardTitle>
          <CardDescription>
            {latest
              ? `Read from TM1 ${ago(latest.started_at)}: ${latest.object_count} objects, ${latest.relationship_count} dependencies. Refreshed daily, and after each change approved here.`
              : "Not read from TM1 yet. Extract it to answer dependency and impact questions."}
          </CardDescription>
          {stale ? (
            <p className="text-xs text-warning">
              Over {STALE_AFTER_DAYS} days old — answers may miss recent changes.
            </p>
          ) : null}
        </div>
        <Button size="sm" variant="outline" onClick={onExtract} disabled={extracting}>
          {extracting ? (
            <Loader2 className="size-4 animate-spin" aria-hidden />
          ) : (
            <RefreshCw className="size-4" aria-hidden />
          )}
          Extract now
        </Button>
      </CardHeader>
      <CardContent>
        {history.isPending ? (
          <Skeleton className="h-16 w-full" />
        ) : history.isError ? (
          <p className="text-sm text-destructive">Could not load the history.</p>
        ) : !history.data?.length ? null : (
          <ul className="divide-y">
            {history.data.map((record) => {
              const counts = record.changes?.counts;
              const changed =
                counts &&
                counts.objects_added + counts.objects_removed + counts.relationships_added + counts.relationships_removed;
              return (
                <li key={record.id} className="space-y-2 py-3">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span>{new Date(record.started_at).toLocaleString()}</span>
                    <Badge variant="outline">{record.trigger === "schedule" ? "daily" : "manual"}</Badge>
                    {record.status === "failed" ? (
                      <Badge variant="destructive">failed</Badge>
                    ) : record.changes?.first ? (
                      <span className="text-xs text-muted-foreground">first read</span>
                    ) : changed ? (
                      <span className="text-xs text-muted-foreground">
                        {counts.objects_added} added · {counts.objects_removed} removed ·{" "}
                        {counts.relationships_added + counts.relationships_removed} dependencies changed
                      </span>
                    ) : (
                      <span className="text-xs text-muted-foreground">no changes</span>
                    )}
                  </div>
                  {record.status === "failed" && record.error_message ? (
                    <p className="text-xs text-destructive">{record.error_message}</p>
                  ) : null}
                  {record.changes && !record.changes.first && changed ? (
                    <div className="grid gap-3 sm:grid-cols-2">
                      <ChangeList
                        title="New objects"
                        items={record.changes.objects_added.map((o) => `${o.type} ${o.name}`)}
                      />
                      <ChangeList
                        title="Removed objects"
                        items={record.changes.objects_removed.map((o) => `${o.type} ${o.name}`)}
                      />
                      <ChangeList
                        title="New dependencies"
                        items={record.changes.relationships_added.map(edgeText)}
                      />
                      <ChangeList
                        title="Removed dependencies"
                        items={record.changes.relationships_removed.map(edgeText)}
                      />
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
