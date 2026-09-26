"use client";

import { useQuery } from "@tanstack/react-query";
import { BarChart3, Loader2 } from "lucide-react";

import { ChartBuilder } from "@/components/visualize/chart-builder";
import { ApiError, apiRequest } from "@/lib/api-client";
import type { ChatChart } from "@/lib/chat-charts";
import { tableFrom, type VisualizeResult } from "@/lib/visualize";

/**
 * A chart the analyst showed in Chat. The query is re-run here rather than
 * read from the tool's result, which only carries the preview the model
 * explains from; the chart gets every row, and the same builder as the
 * Visualize page to re-cut it.
 */
export function ChatChartCard({ chart }: { chart: ChatChart }) {
  const result = useQuery({
    queryKey: ["chat-chart", chart.executionId],
    queryFn: () =>
      apiRequest<VisualizeResult>(
        `/tm1/connections/${chart.connectionId}/visualize/run`,
        {
          method: "POST",
          body: { mdx: chart.mdx },
        },
      ),
    staleTime: Infinity,
    retry: false,
  });

  return (
    <div className="rounded-lg border bg-card p-3" data-testid="chat-chart">
      <div className="mb-2 flex items-center gap-2 text-sm font-medium">
        <BarChart3 className="h-4 w-4" />
        {chart.title || result.data?.cube_name || "Chart"}
      </div>
      {result.isPending ? (
        <p
          role="status"
          className="flex items-center gap-2 text-xs text-muted-foreground"
        >
          <Loader2 className="h-3 w-3 animate-spin" />
          Loading the chart…
        </p>
      ) : result.isError ? (
        <p className="text-xs text-destructive">
          {result.error instanceof ApiError
            ? result.error.message
            : "The chart could not be loaded."}
        </p>
      ) : (
        <ChartBuilder
          table={tableFrom(result.data)}
          title={chart.title || result.data.cube_name}
          initialType={chart.visual}
          compact
        />
      )}
    </div>
  );
}
