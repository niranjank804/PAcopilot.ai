/**
 * The Visualize page's data layer: a TM1 result as a table, pivoted into
 * whatever the chart needs.
 *
 * The backend returns one row per cell with each dimension kept separate.
 * Everything here — which dimension is the axis, which is the legend,
 * slicers on the rest, sort, top N, "Other" — happens in the browser, so
 * changing the view never costs another AI call or TM1 query.
 */

export interface VisualizeRow {
  members: Record<string, string>;
  value: number | string | null;
}

export interface VisualizeTable {
  dimensions: string[];
  rows: VisualizeRow[];
  truncated: boolean;
}

export interface VisualizeResult {
  cube_name: string;
  mdx: string;
  summary?: string;
  cells?: { label: string; value: number | string | null }[];
  table?: VisualizeTable | null;
}

/** Legend entries shown before the rest fold into "Other". Eight is the
 * number of categorical colours that stay distinguishable. */
export const MAX_SERIES = 8;
export const OTHER = "Other";
/** The single series when no legend dimension is chosen. */
export const VALUE = "Value";

export type SortOrder = "natural" | "value-desc" | "value-asc" | "label";
export type NumberFormat = "auto" | "compact" | "thousands" | "millions" | "percent";

export interface PivotOptions {
  axis: string;
  series: string | null;
  /** Dimension -> selected member; absent means "all, summed". */
  filters: Record<string, string>;
  sort: SortOrder;
  topN: number | null;
}

export interface PivotResult {
  categories: string[];
  series: string[];
  /** One object per category: {category, <series>: number, ...}. */
  data: Record<string, number | string>[];
  /** Dimensions summed because they are neither axis, legend nor filtered. */
  summed: string[];
  /** Cells that were text or empty, left out of the numbers. */
  nonNumeric: number;
  foldedSeries: number;
  total: number;
}

export function numeric(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** An older response has only "a|b|c" labels. Rebuild a one-dimension
 * table from them so the builder still works. */
export function tableFrom(result: VisualizeResult): VisualizeTable {
  if (result.table && result.table.rows.length) return result.table;

  return {
    dimensions: ["Member"],
    rows: (result.cells ?? []).map((cell) => ({
      members: { Member: cell.label },
      value: cell.value,
    })),
    truncated: false,
  };
}

export function membersOf(table: VisualizeTable, dimension: string): string[] {
  const seen = new Set<string>();
  for (const row of table.rows) {
    const member = row.members[dimension];
    if (member !== undefined) seen.add(member);
  }
  return Array.from(seen);
}

const TIME_LIKE = /period|month|year|time|date|week|quarter|day/i;

/** A sensible first view: time (or the widest dimension) on the axis, the
 * next dimension as the legend when it is small enough to read. */
export function defaultView(table: VisualizeTable): { axis: string; series: string | null } {
  const dims = table.dimensions;
  if (!dims.length) return { axis: "", series: null };

  const counts = new Map(dims.map((d) => [d, membersOf(table, d).length]));
  const varying = dims.filter((d) => (counts.get(d) ?? 0) > 1);
  const pool = varying.length ? varying : dims;

  const axis =
    pool.find((d) => TIME_LIKE.test(d)) ??
    [...pool].sort((a, b) => (counts.get(b) ?? 0) - (counts.get(a) ?? 0))[0];

  const series =
    pool.find((d) => d !== axis && (counts.get(d) ?? 0) <= MAX_SERIES) ?? null;

  return { axis, series };
}

export function pivot(table: VisualizeTable, options: PivotOptions): PivotResult {
  const { axis, series, filters, sort, topN } = options;

  const summed = table.dimensions.filter(
    (d) => d !== axis && d !== series && !(d in filters),
  );

  const categoryOrder: string[] = [];
  const seriesTotals = new Map<string, number>();
  const cells = new Map<string, Map<string, number>>();
  let nonNumeric = 0;

  for (const row of table.rows) {
    if (Object.entries(filters).some(([d, m]) => row.members[d] !== m)) continue;

    const value = numeric(row.value);
    if (value === null) {
      nonNumeric += 1;
      continue;
    }

    const category = row.members[axis] ?? "";
    const name = series ? row.members[series] ?? "" : VALUE;

    if (!cells.has(category)) {
      cells.set(category, new Map());
      categoryOrder.push(category);
    }
    const bucket = cells.get(category)!;
    bucket.set(name, (bucket.get(name) ?? 0) + value);
    seriesTotals.set(name, (seriesTotals.get(name) ?? 0) + Math.abs(value));
  }

  // Keep the largest series; the tail becomes "Other" rather than a
  // colour nobody can tell apart.
  const rankedSeries = [...seriesTotals.keys()].sort(
    (a, b) => (seriesTotals.get(b) ?? 0) - (seriesTotals.get(a) ?? 0),
  );
  const kept =
    rankedSeries.length > MAX_SERIES
      ? new Set(rankedSeries.slice(0, MAX_SERIES - 1))
      : new Set(rankedSeries);
  const seriesNames = series
    ? membersOf(table, series).filter((s) => kept.has(s))
    : [VALUE];
  const folded = rankedSeries.length - kept.size;
  if (folded > 0) seriesNames.push(OTHER);

  let data = categoryOrder.map((category) => {
    const entry: Record<string, number | string> = { category };
    for (const [name, value] of cells.get(category)!) {
      const key = kept.has(name) ? name : OTHER;
      entry[key] = ((entry[key] as number | undefined) ?? 0) + value;
    }
    return entry;
  });

  const rowTotal = (entry: Record<string, number | string>) =>
    seriesNames.reduce((sum, s) => sum + ((entry[s] as number | undefined) ?? 0), 0);

  if (sort === "value-desc") data.sort((a, b) => rowTotal(b) - rowTotal(a));
  if (sort === "value-asc") data.sort((a, b) => rowTotal(a) - rowTotal(b));
  if (sort === "label")
    data.sort((a, b) =>
      String(a.category).localeCompare(String(b.category), undefined, { numeric: true }),
    );

  if (topN && data.length > topN) data = data.slice(0, topN);

  return {
    categories: data.map((d) => String(d.category)),
    series: seriesNames,
    data,
    summed,
    nonNumeric,
    foldedSeries: folded,
    total: data.reduce((sum, entry) => sum + rowTotal(entry), 0),
  };
}

/** Each category's share of its own total, for a 100% stacked chart. */
export function asPercentOfCategory(result: PivotResult): Record<string, number | string>[] {
  return result.data.map((entry) => {
    const total = result.series.reduce(
      (sum, s) => sum + Math.abs((entry[s] as number | undefined) ?? 0),
      0,
    );
    const out: Record<string, number | string> = { category: entry.category };
    for (const s of result.series) {
      out[s] = total ? (((entry[s] as number | undefined) ?? 0) / total) * 100 : 0;
    }
    return out;
  });
}

/** Running totals for a waterfall: an invisible base and a visible step. */
export function waterfall(result: PivotResult): {
  category: string;
  base: number;
  rise: number;
  fall: number;
  value: number;
}[] {
  const series = result.series[0];
  let running = 0;

  return result.data.map((entry) => {
    const value = (entry[series] as number | undefined) ?? 0;
    const start = running;
    running += value;
    return {
      category: String(entry.category),
      base: Math.min(start, running),
      rise: value >= 0 ? value : 0,
      fall: value < 0 ? -value : 0,
      value,
    };
  });
}

export function formatNumber(value: number, format: NumberFormat, total = 0): string {
  if (!Number.isFinite(value)) return "";

  switch (format) {
    case "compact":
      return new Intl.NumberFormat(undefined, {
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(value);
    case "thousands":
      return `${(value / 1_000).toLocaleString(undefined, { maximumFractionDigits: 1 })}K`;
    case "millions":
      return `${(value / 1_000_000).toLocaleString(undefined, { maximumFractionDigits: 2 })}M`;
    case "percent":
      return total ? `${((value / total) * 100).toFixed(1)}%` : "";
    default:
      return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
}

function csvField(value: unknown): string {
  const text = value === null || value === undefined ? "" : String(value);
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** The pivoted view as CSV: axis down, legend across. */
export function pivotToCsv(result: PivotResult, axisLabel: string): string {
  const header = [axisLabel, ...result.series].map(csvField).join(",");
  const lines = result.data.map((entry) =>
    [entry.category, ...result.series.map((s) => entry[s] ?? "")].map(csvField).join(","),
  );
  return [header, ...lines].join("\r\n");
}

/** Every cell as returned, one column per dimension. */
export function tableToCsv(table: VisualizeTable): string {
  const header = [...table.dimensions, "Value"].map(csvField).join(",");
  const lines = table.rows.map((row) =>
    [...table.dimensions.map((d) => row.members[d] ?? ""), row.value].map(csvField).join(","),
  );
  return [header, ...lines].join("\r\n");
}
