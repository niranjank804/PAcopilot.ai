import { expect, test, type Page } from "@playwright/test";

import { API, signIn, stubApi } from "./fixtures/stub-api";

/**
 * Every visual type, rendered in a real browser from one stubbed result:
 * 12 months × 3 versions × 4 regions. Screenshots are attached for a
 * person to look at; the assertions catch sideways scrolling and a chart
 * that renders nothing.
 */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const VERSIONS = ["Actual", "Budget", "Forecast"];
const REGIONS = ["North", "South", "East", "West"];

const rows = MONTHS.flatMap((month, m) =>
  VERSIONS.flatMap((version, v) =>
    REGIONS.map((region, r) => ({
      members: { Period: `${month}-2026`, Version: version, Region: region },
      value: Math.round(100_000 + m * 4_000 + v * 6_000 - r * 9_000 + ((m * 7 + r * 3) % 5) * 2_500),
    })),
  ),
);

const RESULT = {
  cube_name: "Sales",
  mdx: "SELECT {[Period].[Period].Members} ON COLUMNS, {[Version].[Version].Members} * {[Region].[Region].Members} ON ROWS FROM [Sales]",
  summary: "Revenue rises through the year; Actual tracks above Budget from May.",
  cells: [],
  table: { dimensions: ["Period", "Version", "Region"], rows, truncated: false },
};

const VISUALS = [
  "Column",
  "Bar (horizontal)",
  "Stacked column",
  "100% stacked",
  "Line",
  "Area",
  "Pie",
  "Donut",
  "Treemap",
  "Heatmap",
  "Waterfall",
  "KPI cards",
  "Matrix",
];

async function openWithResult(page: Page) {
  await page.route(`${API}/tm1/connections/c1/visualize`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ success: true, data: RESULT }),
    }),
  );

  await page.goto("/visualize");
  await page.getByRole("combobox", { name: "Connection" }).click();
  await page.getByRole("option", { name: "fpa" }).click();
  await page.getByRole("textbox", { name: "Data question" }).fill("Revenue by month");
  await page.getByRole("button", { name: "Visualize" }).click();
  await expect(page.getByRole("combobox", { name: "Visual" })).toBeVisible();
}

async function noSidewaysScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
}

test.beforeEach(async ({ context }) => {
  await stubApi(context);
  await signIn(context);
});

for (const [label, width] of [
  ["desktop", 1280],
  ["phone", 390],
] as const) {
  test(`every visual renders on ${label}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await openWithResult(page);

    for (const visual of VISUALS) {
      await page.getByRole("combobox", { name: "Visual" }).click();
      await page.getByRole("option", { name: visual, exact: true }).click();

      const htmlView = ["Heatmap", "KPI cards", "Matrix"].includes(visual);
      if (htmlView) {
        await expect(page.getByRole("table").or(page.getByText("Total")).first()).toBeVisible();
      } else {
        // Recharts draws something into its SVG surface.
        await expect(page.locator("svg.recharts-surface").first()).toBeVisible();
        const marks = await page
          .locator(
            "svg.recharts-surface path, svg.recharts-surface rect, svg.recharts-surface circle",
          )
          .count();
        expect(marks, `${visual} drew no marks`).toBeGreaterThan(3);
      }

      await noSidewaysScroll(page);
      const shot = await page.getByTestId("viz-builder").screenshot();
      await testInfo.attach(`${label}-${visual}`, { body: shot, contentType: "image/png" });
      // For looking at, not asserting: VIZ_SHOTS=<dir> saves each one.
      if (process.env.VIZ_SHOTS) {
        const { writeFile } = await import("node:fs/promises");
        await writeFile(`${process.env.VIZ_SHOTS}/${label}-${visual.replace(/\W+/g, "_")}.png`, shot);
      }
    }
  });
}

test("edited MDX re-runs without the AI", async ({ page }) => {
  let ran = "";
  await page.route(`${API}/tm1/connections/c1/visualize/run`, async (route) => {
    ran = (route.request().postDataJSON() as { mdx: string }).mdx;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: { ...RESULT, mdx: ran, table: { ...RESULT.table, rows: rows.slice(0, 12) } },
      }),
    });
  });

  await openWithResult(page);
  await page.getByRole("button", { name: "Edit MDX" }).click();
  await page.getByRole("textbox", { name: "MDX query" }).fill("SELECT {[Period].[Jan-2026]} ON 0 FROM [Sales]");
  await page.getByRole("button", { name: "Run query" }).click();

  await expect(page.getByText("12 cell(s) · 3 dimension(s)")).toBeVisible();
  expect(ran).toContain("[Jan-2026]");
});

test("charts use the dark palette in dark mode", async ({ page }, testInfo) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await openWithResult(page);

  for (const visual of ["Line", "Stacked column", "Heatmap"]) {
    await page.getByRole("combobox", { name: "Visual" }).click();
    await page.getByRole("option", { name: visual, exact: true }).click();
    const shot = await page.getByTestId("viz-builder").screenshot();
    await testInfo.attach(`dark-${visual}`, { body: shot, contentType: "image/png" });
    if (process.env.VIZ_SHOTS) {
      const { writeFile } = await import("node:fs/promises");
      await writeFile(`${process.env.VIZ_SHOTS}/dark-${visual.replace(/\W+/g, "_")}.png`, shot);
    }
  }

  // Slot 1 of the dark palette, not the light one.
  await page.getByRole("combobox", { name: "Visual" }).click();
  await page.getByRole("option", { name: "Line", exact: true }).click();
  await expect(page.locator('svg.recharts-surface path[stroke="#3987e5"]').first()).toBeVisible();
});
