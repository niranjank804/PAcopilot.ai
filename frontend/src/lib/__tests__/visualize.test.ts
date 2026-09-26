import { describe, expect, it } from "vitest";

import {
  MAX_SERIES,
  OTHER,
  VALUE,
  asPercentOfCategory,
  defaultView,
  formatNumber,
  pivot,
  pivotToCsv,
  tableFrom,
  tableToCsv,
  waterfall,
  type VisualizeTable,
} from "../visualize";

const TABLE: VisualizeTable = {
  dimensions: ["Period", "Version", "Region"],
  rows: [
    { members: { Period: "Jan", Version: "Actual", Region: "North" }, value: 10 },
    { members: { Period: "Jan", Version: "Actual", Region: "South" }, value: 5 },
    { members: { Period: "Jan", Version: "Budget", Region: "North" }, value: 12 },
    { members: { Period: "Feb", Version: "Actual", Region: "North" }, value: 20 },
    { members: { Period: "Feb", Version: "Budget", Region: "South" }, value: "n/a" },
  ],
  truncated: false,
};

const view = (overrides = {}) =>
  pivot(TABLE, {
    axis: "Period",
    series: "Version",
    filters: {},
    sort: "natural",
    topN: null,
    ...overrides,
  });

describe("pivot", () => {
  it("puts the axis down and the legend across, summing the rest", () => {
    const result = view();

    expect(result.categories).toEqual(["Jan", "Feb"]);
    expect(result.series).toEqual(["Actual", "Budget"]);
    expect(result.data[0]).toEqual({ category: "Jan", Actual: 15, Budget: 12 });
    expect(result.summed).toEqual(["Region"]);
  });

  it("slices a dimension to one member", () => {
    const result = view({ filters: { Region: "North" } });

    expect(result.data[0]).toEqual({ category: "Jan", Actual: 10, Budget: 12 });
    expect(result.summed).toEqual([]);
  });

  it("leaves text cells out and counts them", () => {
    expect(view().nonNumeric).toBe(1);
  });

  it("uses one series when there is no legend", () => {
    const result = view({ series: null });

    expect(result.series).toEqual([VALUE]);
    expect(result.data[0]).toEqual({ category: "Jan", [VALUE]: 27 });
  });

  it("sorts and keeps the top N", () => {
    const result = view({ series: null, sort: "value-desc", topN: 1 });

    // Jan 10+5+12 = 27 beats Feb 20 (its text cell is left out).
    expect(result.categories).toEqual(["Jan"]);
  });

  it("folds the smallest series into Other past the colour limit", () => {
    const rows = Array.from({ length: 12 }, (_, i) => ({
      members: { Period: "Jan", Account: `A${i}` },
      value: i + 1,
    }));
    const result = pivot(
      { dimensions: ["Period", "Account"], rows, truncated: false },
      { axis: "Period", series: "Account", filters: {}, sort: "natural", topN: null },
    );

    expect(result.series).toHaveLength(MAX_SERIES);
    expect(result.series.at(-1)).toBe(OTHER);
    // A11..A5 kept (7 largest); A0..A4 (1+2+3+4+5) folded.
    expect(result.data[0][OTHER]).toBe(15);
    expect(result.foldedSeries).toBe(5);
  });
});

describe("derived views", () => {
  it("turns each category into shares of its own total", () => {
    const [jan] = asPercentOfCategory(view());

    expect(Number(jan.Actual) + Number(jan.Budget)).toBeCloseTo(100);
  });

  it("builds waterfall steps from a running total", () => {
    const steps = waterfall(
      pivot(
        {
          dimensions: ["Step"],
          rows: [
            { members: { Step: "Open" }, value: 100 },
            { members: { Step: "Cost" }, value: -30 },
          ],
          truncated: false,
        },
        { axis: "Step", series: null, filters: {}, sort: "natural", topN: null },
      ),
    );

    expect(steps[0]).toMatchObject({ base: 0, rise: 100, fall: 0 });
    expect(steps[1]).toMatchObject({ base: 70, rise: 0, fall: 30 });
  });

  it("chooses time for the axis and a small dimension for the legend", () => {
    expect(defaultView(TABLE)).toEqual({ axis: "Period", series: "Version" });
  });

  it("rebuilds a table from an older response's labels", () => {
    const table = tableFrom({ cube_name: "Sales", mdx: "x", cells: [{ label: "Jan|Actual", value: 1 }] });

    expect(table.dimensions).toEqual(["Member"]);
    expect(table.rows[0].value).toBe(1);
  });
});

describe("formatting and export", () => {
  it("formats numbers the ways the picker offers", () => {
    expect(formatNumber(1_500_000, "millions")).toBe("1.5M");
    expect(formatNumber(2500, "thousands")).toBe("2.5K");
    expect(formatNumber(25, "percent", 200)).toBe("12.5%");
  });

  it("writes CSV with quoting where needed", () => {
    const csv = pivotToCsv(view(), "Period");

    expect(csv.split("\r\n")[0]).toBe("Period,Actual,Budget");
    expect(tableToCsv({ dimensions: ["A"], rows: [{ members: { A: 'x, "y"' }, value: 1 }], truncated: false }))
      .toContain('"x, ""y"""');
  });
});
