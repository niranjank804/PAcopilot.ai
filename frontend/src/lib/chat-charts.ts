import type { ChartType } from "@/components/visualize/chart-builder";
import type { ToolExecutionResponse } from "@/lib/types";

/**
 * Charts in Chat.
 *
 * The analyst's `show_chart` tool records the query it charted in the
 * conversation's tool log (connection, MDX, title). The page reads charts
 * from there and re-runs the query through /visualize/run, so the chart
 * always has every row — the tool's own result is only the preview the
 * model explains from — and a reopened conversation redraws its charts.
 */

export const CHART_TOOL = "show_chart";

export interface ChatChart {
  executionId: string;
  connectionId: string;
  mdx: string;
  title: string;
  visual?: ChartType;
}

const VISUALS = new Set<string>([
  "column",
  "bar",
  "stacked",
  "stacked100",
  "line",
  "area",
  "pie",
  "donut",
  "treemap",
  "heatmap",
  "waterfall",
  "kpi",
  "matrix",
]);

/** The chart a tool execution drew, or null if it drew none. */
export function chartFrom(execution: ToolExecutionResponse): ChatChart | null {
  if (execution.tool_name !== CHART_TOOL || execution.status !== "success") {
    return null;
  }
  // The tool answers {"shown": false, ...} when the query was empty.
  if (/"shown":\s*false/.test(execution.result_summary ?? "")) return null;

  const { connection_id, mdx, title, visual } = execution.arguments;
  if (typeof connection_id !== "string" || typeof mdx !== "string") return null;

  return {
    executionId: execution.id,
    connectionId: connection_id,
    mdx,
    title: typeof title === "string" ? title : "",
    visual:
      typeof visual === "string" && VISUALS.has(visual)
        ? (visual as ChartType)
        : undefined,
  };
}

/** Charts not yet shown on any message, oldest first. */
export function newCharts(
  executions: ToolExecutionResponse[],
  shown: Set<string>,
): ChatChart[] {
  return [...executions]
    .sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at))
    .map(chartFrom)
    .filter(
      (chart): chart is ChatChart =>
        chart !== null && !shown.has(chart.executionId),
    );
}

interface Placeable {
  role: "user" | "assistant";
  createdAt?: string;
}

/**
 * For a reopened conversation: which assistant message each chart belongs
 * to. A chart is drawn during a turn, so it belongs to the first assistant
 * message saved at or after it (the answer is saved when the turn ends).
 * Returns a chart list per message index.
 */
export function placeCharts(
  messages: Placeable[],
  executions: ToolExecutionResponse[],
): Map<number, ChatChart[]> {
  const placed = new Map<number, ChatChart[]>();
  const assistantIndexes = messages
    .map((message, index) => ({ message, index }))
    .filter(({ message }) => message.role === "assistant");
  if (!assistantIndexes.length) return placed;

  for (const chart of newCharts(executions, new Set())) {
    const execution = executions.find((e) => e.id === chart.executionId)!;
    const drawnAt = Date.parse(execution.created_at);
    const owner =
      assistantIndexes.find(
        ({ message }) =>
          message.createdAt && Date.parse(message.createdAt) >= drawnAt,
      ) ?? assistantIndexes[assistantIndexes.length - 1];
    placed.set(owner.index, [...(placed.get(owner.index) ?? []), chart]);
  }

  return placed;
}
