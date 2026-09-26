"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { BarChart3, Code2, Loader2, Play, Sparkles } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ChartBuilder } from "@/components/visualize/chart-builder";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, apiRequest } from "@/lib/api-client";
import type { TM1Connection } from "@/lib/types";
import { tableFrom, type VisualizeResult, type VisualizeTable } from "@/lib/visualize";

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong.";
}

const EXAMPLES = [
  "Revenue by month for 2026, actual vs budget",
  "Headcount by department for the current year",
  "Top 10 accounts by expense this year",
  "Operating expense by quarter and region",
];

interface ShownResult {
  cubeName: string;
  mdx: string;
  summary: string;
  table: VisualizeTable;
  /** Bumped on every new result so the builder starts from a fresh view. */
  version: number;
}

export default function VisualizePage() {
  const [connectionId, setConnectionId] = useState<string>("");
  const [query, setQuery] = useState("");
  const [shown, setShown] = useState<ShownResult | null>(null);
  const [mdxDraft, setMdxDraft] = useState("");
  const [editing, setEditing] = useState(false);

  const connectionsQuery = useQuery({
    queryKey: ["tm1-connections"],
    queryFn: () => apiRequest<TM1Connection[]>("/tm1/connections"),
  });

  const show = (result: VisualizeResult, summary: string) => {
    setShown((previous) => ({
      cubeName: result.cube_name,
      mdx: result.mdx,
      summary,
      table: tableFrom(result),
      version: (previous?.version ?? 0) + 1,
    }));
    setMdxDraft(result.mdx);
  };

  const visualizeMutation = useMutation({
    mutationFn: () =>
      apiRequest<VisualizeResult>(`/tm1/connections/${connectionId}/visualize`, {
        method: "POST",
        body: { query },
      }),
    onSuccess: (data) => {
      show(data, data.summary ?? "");
      setEditing(false);
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const runMutation = useMutation({
    mutationFn: () =>
      apiRequest<VisualizeResult>(`/tm1/connections/${connectionId}/visualize/run`, {
        method: "POST",
        body: { mdx: mdxDraft },
      }),
    onSuccess: (data) => {
      show(data, "Your edited query, run directly against TM1.");
      toast.success(`Query ran — ${data.table?.rows.length ?? 0} cell(s).`);
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="page-title">Visualize</h1>
        <p className="text-sm text-muted-foreground">
          Ask a data question in plain language. The Analyst agent finds the
          cube, confirms real element names and writes the MDX; then build the
          view you want — axis, legend, slicers, 13 visual types — without
          asking again.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Ask a data question</CardTitle>
          <CardDescription>
            Name the measure and period for the best result. Up to 2,000
            cells come back; everything after that is pivoting in your
            browser.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-0 flex-1 space-y-2">
              <Textarea
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Revenue by month for 2026, actual vs budget"
                rows={3}
                aria-label="Data question"
              />
            </div>
            <Select
              value={connectionId}
              onValueChange={(value) => setConnectionId(value ?? "")}
            >
              <SelectTrigger className="w-56 max-w-full" aria-label="Connection">
                {/* Base UI renders the raw value unless given a function
                    child — without this the trigger shows the connection's
                    UUID instead of its name. */}
                <SelectValue placeholder="Select connection">
                  {(value: string) =>
                    connectionsQuery.data?.find((c) => c.id === value)?.name ??
                    "Select connection"
                  }
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {connectionsQuery.data?.map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-wrap gap-2">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => setQuery(example)}
                className="rounded-full border px-3 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                {example}
              </button>
            ))}
          </div>
          <Button
            onClick={() => visualizeMutation.mutate()}
            disabled={visualizeMutation.isPending || !query.trim() || !connectionId}
          >
            {visualizeMutation.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="mr-2 h-4 w-4" />
            )}
            {visualizeMutation.isPending ? "Finding the data…" : "Visualize"}
          </Button>
          {visualizeMutation.isPending ? (
            <p role="status" className="text-xs text-muted-foreground">
              The agent is reading the cube and testing the query. This
              usually takes 15–45 seconds.
            </p>
          ) : null}
        </CardContent>
      </Card>

      {shown ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <BarChart3 className="h-4 w-4" />
              {shown.cubeName || "Results"}
            </CardTitle>
            {shown.summary ? <CardDescription>{shown.summary}</CardDescription> : null}
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" variant="ghost" onClick={() => setEditing((v) => !v)}>
                  <Code2 className="mr-2 h-3.5 w-3.5" />
                  {editing ? "Hide MDX" : "Edit MDX"}
                </Button>
                <span className="text-xs text-muted-foreground">
                  {shown.table.rows.length.toLocaleString()} cell(s) ·{" "}
                  {shown.table.dimensions.length} dimension(s)
                </span>
              </div>
              {editing ? (
                <div className="space-y-2">
                  <Textarea
                    value={mdxDraft}
                    onChange={(e) => setMdxDraft(e.target.value)}
                    rows={6}
                    className="font-mono text-xs"
                    aria-label="MDX query"
                  />
                  <Button
                    size="sm"
                    onClick={() => runMutation.mutate()}
                    disabled={runMutation.isPending || !mdxDraft.trim() || !connectionId}
                  >
                    {runMutation.isPending ? (
                      <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Play className="mr-2 h-3.5 w-3.5" />
                    )}
                    Run query
                  </Button>
                  <p className="text-xs text-muted-foreground">
                    Runs straight against TM1 — no AI, no quota. MDX only
                    reads; it cannot change data.
                  </p>
                </div>
              ) : (
                <pre className="max-h-32 overflow-auto rounded-md bg-muted p-3 text-xs">
                  {shown.mdx}
                </pre>
              )}
            </div>

            {shown.table.rows.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                The query ran but returned no cells (empty cells are left out).
              </p>
            ) : (
              <ChartBuilder
                key={shown.version}
                table={shown.table}
                title={shown.cubeName || "chart"}
              />
            )}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
