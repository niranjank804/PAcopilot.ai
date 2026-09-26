import { expect, test, type Page } from "@playwright/test";

import { API, signIn, stubApi } from "./fixtures/stub-api";

/**
 * A chart the analyst shows in Chat, in a real browser: drawn under the
 * answer, usable at phone width, and redrawn when the conversation is
 * reopened.
 */

const MONTHS = ["202601", "202602", "202603", "202604", "202605", "202606"];

const EXECUTION = {
  id: "exec-chart",
  tool_name: "show_chart",
  arguments: {
    connection_id: "c1",
    mdx: "SELECT {[Period].Members} ON 0, {[Version].[Plan],[Version].[Actual]} ON 1 FROM [Income]",
    title: "Revenue by month, 2026",
    visual: "line",
  },
  status: "success",
  result_summary: '{"shown": true}',
  duration_ms: 50,
  error_message: null,
  created_at: "2026-09-26T10:00:05Z",
};

const RESULT = {
  cube_name: "Income",
  mdx: EXECUTION.arguments.mdx,
  cells: [],
  table: {
    dimensions: ["Period", "Version"],
    rows: MONTHS.flatMap((period, m) => [
      {
        members: { Period: period, Version: "Plan" },
        value: 4_500_000_000 + m * 60_000_000,
      },
      {
        members: { Period: period, Version: "Actual" },
        value: 4_400_000_000 + m * 75_000_000,
      },
    ]),
    truncated: false,
  },
};

const ANSWER =
  "Revenue rises steadily through the first half of 2026. Actuals start " +
  "just under Plan and overtake it by May.";

function sse(events: unknown[]) {
  return events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
}

async function stubChart(page: Page) {
  await page.route(`${API}/ai/agents`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: [
          {
            name: "analyst",
            description: "Data questions",
            max_tool_rounds: 10,
            tool_names: ["execute_mdx", "show_chart"],
            safety_notes: null,
          },
        ],
      }),
    }),
  );
  await page.route(`${API}/ai/chat/stream`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: sse([
        { type: "start", conversation_id: "conv1" },
        { type: "tool_call", tool_name: "execute_mdx", tool_status: "success" },
        { type: "tool_call", tool_name: "show_chart", tool_status: "success" },
        { type: "text_delta", text: ANSWER },
        {
          type: "done",
          conversation_id: "conv1",
          message_id: "m1",
          usage: { input_tokens: 10, output_tokens: 5 },
          estimated_cost_usd: 0.01,
        },
      ]),
    }),
  );
  await page.route(`${API}/ai/conversations/conv1/tool-executions`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ success: true, data: [EXECUTION] }),
    }),
  );
  await page.route(`${API}/tm1/connections/c1/visualize/run`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ success: true, data: RESULT }),
    }),
  );
}

test.beforeEach(async ({ context }) => {
  await stubApi(context);
  await signIn(context);
});

for (const [label, width] of [
  ["desktop", 1280],
  ["phone", 390],
] as const) {
  test(`a chart request shows the chart under the answer on ${label}`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await stubChart(page);
    await page.goto("/chat");

    const box = page.getByPlaceholder(/what do you want to accomplish/i);
    await box.fill("Chart revenue by month for 2026, actual vs plan");
    await box.press("Enter");

    await expect(page.getByText(/overtake it by May/)).toBeVisible();
    const chart = page.getByTestId("chat-chart");
    await expect(chart).toBeVisible();
    await expect(chart).toContainText("Revenue by month, 2026");
    await expect(chart.locator("svg.recharts-surface").first()).toBeVisible();
    // The chart shows first; its options wait behind a button.
    await expect(
      chart.getByRole("button", { name: "Customize chart" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Read aloud" }),
    ).toBeVisible();

    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);

    const shot = await page.locator("main").screenshot();
    await testInfo.attach(`chat-chart-${label}`, {
      body: shot,
      contentType: "image/png",
    });
    if (process.env.VIZ_SHOTS) {
      const { writeFile } = await import("node:fs/promises");
      await writeFile(`${process.env.VIZ_SHOTS}/chat-chart-${label}.png`, shot);
      await writeFile(
        `${process.env.VIZ_SHOTS}/chat-chart-${label}-card.png`,
        await chart.screenshot(),
      );
    }
  });
}
