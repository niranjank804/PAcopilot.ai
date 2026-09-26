import { describe, expect, it } from "vitest";

import { chartFrom, newCharts, placeCharts } from "@/lib/chat-charts";
import type { ToolExecutionResponse } from "@/lib/types";

function execution(
  overrides: Partial<ToolExecutionResponse> = {},
): ToolExecutionResponse {
  return {
    id: "e1",
    tool_name: "show_chart",
    arguments: {
      connection_id: "conn1",
      mdx: "SELECT ... FROM [Income]",
      title: "Revenue by month",
      visual: "line",
    },
    status: "success",
    result_summary: '{"shown": true, "title": "Revenue by month"}',
    duration_ms: 40,
    error_message: null,
    created_at: "2026-09-26T10:00:05Z",
    ...overrides,
  };
}

describe("chartFrom", () => {
  it("reads the chart from a show_chart call", () => {
    expect(chartFrom(execution())).toEqual({
      executionId: "e1",
      connectionId: "conn1",
      mdx: "SELECT ... FROM [Income]",
      title: "Revenue by month",
      visual: "line",
    });
  });

  it("ignores other tools, failed calls and empty results", () => {
    expect(chartFrom(execution({ tool_name: "execute_mdx" }))).toBeNull();
    expect(chartFrom(execution({ status: "error" }))).toBeNull();
    expect(
      chartFrom(
        execution({ result_summary: '{"shown": false, "reason": "no cells"}' }),
      ),
    ).toBeNull();
  });

  it("drops a visual the builder does not know", () => {
    const chart = chartFrom(
      execution({
        arguments: { connection_id: "conn1", mdx: "x", visual: "radar" },
      }),
    );
    expect(chart?.visual).toBeUndefined();
  });
});

describe("newCharts", () => {
  it("returns charts not shown yet, oldest first", () => {
    const executions = [
      execution({ id: "late", created_at: "2026-09-26T10:05:00Z" }),
      execution({ id: "early", created_at: "2026-09-26T10:01:00Z" }),
      execution({ id: "seen", created_at: "2026-09-26T10:00:00Z" }),
    ];

    expect(
      newCharts(executions, new Set(["seen"])).map((c) => c.executionId),
    ).toEqual(["early", "late"]);
  });
});

describe("placeCharts", () => {
  it("puts each chart on the answer saved after it was drawn", () => {
    const messages = [
      { role: "user" as const, createdAt: "2026-09-26T10:00:00Z" },
      { role: "assistant" as const, createdAt: "2026-09-26T10:00:30Z" },
      { role: "user" as const, createdAt: "2026-09-26T10:01:00Z" },
      { role: "assistant" as const, createdAt: "2026-09-26T10:01:40Z" },
    ];
    const executions = [
      execution({ id: "first", created_at: "2026-09-26T10:00:10Z" }),
      execution({ id: "second", created_at: "2026-09-26T10:01:20Z" }),
    ];

    const placed = placeCharts(messages, executions);

    expect(placed.get(1)?.map((c) => c.executionId)).toEqual(["first"]);
    expect(placed.get(3)?.map((c) => c.executionId)).toEqual(["second"]);
  });
});
