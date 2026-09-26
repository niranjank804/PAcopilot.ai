"use client";

import { Download, ImageDown } from "lucide-react";
import { useTheme } from "next-themes";
import { useMemo, useRef, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  Treemap,
  XAxis,
  YAxis,
} from "recharts";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  DIVERGING,
  MUTED,
  type Mode,
  inkOn,
  sequentialColor,
  seriesColor,
} from "@/lib/chart-palette";
import {
  OTHER,
  VALUE,
  asPercentOfCategory,
  defaultView,
  formatNumber,
  membersOf,
  pivot,
  pivotToCsv,
  tableToCsv,
  waterfall,
  type NumberFormat,
  type PivotResult,
  type SortOrder,
  type VisualizeTable,
} from "@/lib/visualize";

export type ChartType =
  | "column"
  | "bar"
  | "stacked"
  | "stacked100"
  | "line"
  | "area"
  | "pie"
  | "donut"
  | "treemap"
  | "heatmap"
  | "waterfall"
  | "kpi"
  | "matrix";

export const CHART_TYPES: { value: ChartType; label: string; help: string }[] =
  [
    {
      value: "column",
      label: "Column",
      help: "Compare values across categories; clustered when there is a legend.",
    },
    {
      value: "bar",
      label: "Bar (horizontal)",
      help: "Like column, for long names or many categories.",
    },
    {
      value: "stacked",
      label: "Stacked column",
      help: "Totals per category, split by the legend.",
    },
    {
      value: "stacked100",
      label: "100% stacked",
      help: "Each category's mix, as shares of its own total.",
    },
    {
      value: "line",
      label: "Line",
      help: "Trends over time; one line per legend member.",
    },
    {
      value: "area",
      label: "Area",
      help: "Volume over time; stacked when there is a legend.",
    },
    {
      value: "pie",
      label: "Pie",
      help: "Part of a whole. Up to 8 slices; the rest become Other.",
    },
    {
      value: "donut",
      label: "Donut",
      help: "Pie with the total in the middle.",
    },
    {
      value: "treemap",
      label: "Treemap",
      help: "Many parts of a whole, sized by value.",
    },
    {
      value: "heatmap",
      label: "Heatmap",
      help: "Axis × legend grid shaded by value — spot highs and lows.",
    },
    {
      value: "waterfall",
      label: "Waterfall",
      help: "How each step adds to or takes from a running total.",
    },
    {
      value: "kpi",
      label: "KPI cards",
      help: "Headline numbers: total, average, highest, lowest.",
    },
    {
      value: "matrix",
      label: "Matrix",
      help: "Pivot table with row and column totals.",
    },
  ];

/** Forms that show one number per category: the legend is summed away. */
const SINGLE_SERIES: ChartType[] = [
  "pie",
  "donut",
  "treemap",
  "waterfall",
  "kpi",
];
/** Forms drawn as SVG, which can be saved as an image. */
const SVG_TYPES: ChartType[] = [
  "column",
  "bar",
  "stacked",
  "stacked100",
  "line",
  "area",
  "pie",
  "donut",
  "treemap",
  "waterfall",
];

const HEIGHTS = { small: 260, medium: 360, large: 520 } as const;
type HeightKey = keyof typeof HEIGHTS;

const SORTS: { value: SortOrder; label: string }[] = [
  { value: "natural", label: "As returned" },
  { value: "value-desc", label: "Largest first" },
  { value: "value-asc", label: "Smallest first" },
  { value: "label", label: "A → Z" },
];

const FORMATS: { value: NumberFormat; label: string }[] = [
  { value: "auto", label: "1,234.5" },
  { value: "compact", label: "1.2K" },
  { value: "thousands", label: "Thousands (K)" },
  { value: "millions", label: "Millions (M)" },
  { value: "percent", label: "% of total" },
];

const TOP_N = ["all", "5", "10", "20", "50"] as const;

const NONE = "__none__";
const ALL = "__all__";

const AXIS_INK = "#898781";

function download(filename: string, content: BlobPart, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function safeName(text: string): string {
  return (text || "chart").replace(/[^\w.-]+/g, "_").slice(0, 60);
}

interface Choice {
  value: string;
  label: string;
}

function Picker({
  id,
  label,
  value,
  choices,
  onChange,
  width = "w-40",
}: {
  id: string;
  label: string;
  value: string;
  choices: Choice[];
  onChange: (value: string) => void;
  width?: string;
}) {
  return (
    <div className="min-w-0 space-y-1.5">
      <Label htmlFor={id} className="text-xs">
        {label}
      </Label>
      <Select value={value} onValueChange={(v) => onChange(String(v ?? value))}>
        <SelectTrigger
          id={id}
          className={`${width} max-w-full`}
          aria-label={label}
        >
          <SelectValue>
            {(current: string) =>
              choices.find((c) => c.value === current)?.label ?? current
            }
          </SelectValue>
        </SelectTrigger>
        <SelectContent>
          {choices.map((choice) => (
            <SelectItem key={choice.value} value={choice.value}>
              {choice.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function Toggle({
  id,
  label,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label htmlFor={id} className="flex items-center gap-1.5 text-xs">
      <input
        id={id}
        type="checkbox"
        className="h-4 w-4 accent-primary"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      {label}
    </label>
  );
}

export interface ChartBuilderProps {
  table: VisualizeTable;
  title: string;
}

/**
 * A Power BI / Tableau style view over one TM1 result.
 *
 * Pick the visual, which dimension runs along the axis and which becomes
 * the legend, slice the remaining dimensions to one member or leave them
 * summed, then sort, keep the top N, format numbers, and export. Every
 * change re-pivots the same rows in the browser.
 */
export function ChartBuilder({ table, title }: ChartBuilderProps) {
  const { resolvedTheme } = useTheme();
  const mode: Mode = resolvedTheme === "dark" ? "dark" : "light";
  const chartRef = useRef<HTMLDivElement>(null);

  const initial = useMemo(() => defaultView(table), [table]);
  // Time on the axis reads best as a line; anything else as columns.
  const [chartType, setChartType] = useState<ChartType>(
    /period|month|year|time|date|week|quarter|day/i.test(initial.axis)
      ? "line"
      : "column",
  );
  const [axis, setAxis] = useState(initial.axis);
  const [series, setSeries] = useState<string | null>(initial.series);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [sort, setSort] = useState<SortOrder>("natural");
  const [topN, setTopN] = useState<(typeof TOP_N)[number]>("all");
  const [format, setFormat] = useState<NumberFormat>("auto");
  const [labels, setLabels] = useState(false);
  const [showLegend, setShowLegend] = useState(true);
  const [grid, setGrid] = useState(true);
  const [height, setHeight] = useState<HeightKey>("medium");

  const singleSeries = SINGLE_SERIES.includes(chartType);
  const effectiveSeries = singleSeries ? null : series;

  const result: PivotResult = useMemo(
    () =>
      pivot(table, {
        axis,
        series: effectiveSeries,
        filters,
        sort,
        topN: topN === "all" ? null : Number(topN),
      }),
    [table, axis, effectiveSeries, filters, sort, topN],
  );

  const slicerDims = table.dimensions.filter(
    (d) =>
      d !== axis && d !== effectiveSeries && membersOf(table, d).length > 1,
  );

  const fmt = (value: unknown) =>
    typeof value === "number"
      ? formatNumber(value, format, result.total)
      : String(value ?? "");
  const tickFmt = (value: unknown) =>
    typeof value === "number"
      ? formatNumber(
          value,
          format === "auto" ? "compact" : format,
          result.total,
        )
      : String(value ?? "");

  const colorOf = (name: string, index: number) =>
    effectiveSeries
      ? seriesColor(index, name, mode)
      : seriesColor(0, name, mode);

  const tooltip = (
    <Tooltip
      formatter={(value) => fmt(value)}
      cursor={{
        fill:
          mode === "dark" ? "rgba(255,255,255,0.06)" : "rgba(11,11,11,0.05)",
      }}
      contentStyle={{
        background: "var(--popover)",
        color: "var(--popover-foreground)",
        border: "1px solid var(--border)",
        borderRadius: 8,
        fontSize: 12,
      }}
    />
  );
  const legend =
    showLegend && result.series.length > 1 ? (
      <Legend wrapperStyle={{ fontSize: 12 }} iconType="circle" />
    ) : null;
  const gridLines = grid ? (
    <CartesianGrid
      strokeDasharray="3 3"
      vertical={false}
      stroke={mode === "dark" ? "#2c2c2a" : "#e1e0d9"}
    />
  ) : null;
  const many = result.categories.length > 8;
  const xAxis = (
    <XAxis
      dataKey="category"
      tick={{ fontSize: 11, fill: AXIS_INK }}
      interval={many ? "preserveStartEnd" : 0}
      angle={many ? -30 : 0}
      textAnchor={many ? "end" : "middle"}
      height={many ? 70 : 30}
      stroke={AXIS_INK}
    />
  );
  const yAxis = (
    <YAxis
      tick={{ fontSize: 11, fill: AXIS_INK }}
      tickFormatter={tickFmt}
      stroke={AXIS_INK}
      width={64}
    />
  );
  const surface = mode === "dark" ? "#1a1a19" : "#fcfcfb";

  const exportPng = () => {
    const svg = chartRef.current?.querySelector("svg.recharts-surface");
    if (!svg) return;
    const { width, height: h } = svg.getBoundingClientRect();
    const clone = svg.cloneNode(true) as SVGSVGElement;
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    const xml = new XMLSerializer().serializeToString(clone);
    const image = new Image();
    const scale = 2;
    image.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = width * scale;
      canvas.height = h * scale;
      const context = canvas.getContext("2d");
      if (!context) return;
      context.fillStyle = surface;
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(
        (blob) => blob && download(`${safeName(title)}.png`, blob, "image/png"),
      );
    };
    image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(xml)}`;
  };

  const notes: string[] = [];
  if (result.summed.length)
    notes.push(
      `Summed across ${result.summed.join(", ")}. Use a slicer to pick one member.`,
    );
  if (result.foldedSeries)
    notes.push(
      `${result.foldedSeries + 1} smaller series are grouped as Other.`,
    );
  if (result.nonNumeric)
    notes.push(
      `${result.nonNumeric} text or empty cell(s) are left out of the chart.`,
    );
  if (table.truncated)
    notes.push(
      "The result was capped at 2,000 cells; narrow the query for the rest.",
    );

  const body = renderChart();

  function renderChart() {
    const data = result.data;

    if (!data.length)
      return (
        <p className="py-10 text-center text-sm text-muted-foreground">
          No numeric values for this selection.
        </p>
      );

    switch (chartType) {
      case "column":
      case "stacked":
      case "stacked100": {
        const stacked = chartType !== "column";
        const rows =
          chartType === "stacked100" ? asPercentOfCategory(result) : data;
        const valueFmt =
          chartType === "stacked100"
            ? (v: unknown) => `${Number(v).toFixed(0)}%`
            : tickFmt;
        return (
          <BarChart
            data={rows}
            barCategoryGap="20%"
            margin={{ top: 8, right: 16, bottom: 4, left: 12 }}
          >
            {gridLines}
            {xAxis}
            <YAxis
              tick={{ fontSize: 11, fill: AXIS_INK }}
              tickFormatter={valueFmt}
              stroke={AXIS_INK}
              width={64}
              domain={chartType === "stacked100" ? [0, 100] : undefined}
            />
            <Tooltip
              formatter={(v) =>
                chartType === "stacked100" ? `${Number(v).toFixed(1)}%` : fmt(v)
              }
              contentStyle={{
                background: "var(--popover)",
                color: "var(--popover-foreground)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                fontSize: 12,
              }}
            />
            {legend}
            {result.series.map((name, index) => (
              <Bar
                key={name}
                dataKey={name}
                stackId={stacked ? "stack" : undefined}
                fill={colorOf(name, index)}
                stroke={stacked ? surface : undefined}
                strokeWidth={stacked ? 1 : 0}
                radius={stacked ? 0 : [4, 4, 0, 0]}
                isAnimationActive={false}
              >
                {labels ? (
                  <LabelList
                    dataKey={name}
                    position={stacked ? "center" : "top"}
                    formatter={(v: unknown) =>
                      chartType === "stacked100"
                        ? `${Number(v).toFixed(0)}%`
                        : tickFmt(v)
                    }
                    style={{
                      fontSize: 10,
                      fill: stacked ? "#ffffff" : AXIS_INK,
                    }}
                  />
                ) : null}
              </Bar>
            ))}
          </BarChart>
        );
      }
      case "bar":
        return (
          <BarChart data={data} layout="vertical" barCategoryGap="20%">
            {grid ? (
              <CartesianGrid
                strokeDasharray="3 3"
                horizontal={false}
                stroke={mode === "dark" ? "#2c2c2a" : "#e1e0d9"}
              />
            ) : null}
            <XAxis
              type="number"
              tick={{ fontSize: 11, fill: AXIS_INK }}
              tickFormatter={tickFmt}
              stroke={AXIS_INK}
            />
            <YAxis
              type="category"
              dataKey="category"
              width={140}
              tick={{ fontSize: 11, fill: AXIS_INK }}
              stroke={AXIS_INK}
              interval={0}
            />
            {tooltip}
            {legend}
            {result.series.map((name, index) => (
              <Bar
                key={name}
                dataKey={name}
                fill={colorOf(name, index)}
                radius={[0, 4, 4, 0]}
                isAnimationActive={false}
              >
                {labels ? (
                  <LabelList
                    dataKey={name}
                    position="right"
                    formatter={tickFmt}
                    style={{ fontSize: 10, fill: AXIS_INK }}
                  />
                ) : null}
              </Bar>
            ))}
          </BarChart>
        );
      case "line":
        return (
          <LineChart
            data={data}
            margin={{ top: 8, right: 16, bottom: 4, left: 12 }}
          >
            {gridLines}
            {xAxis}
            {yAxis}
            {tooltip}
            {legend}
            {result.series.map((name, index) => (
              <Line
                key={name}
                type="monotone"
                dataKey={name}
                stroke={colorOf(name, index)}
                strokeWidth={2}
                dot={{
                  r: 4,
                  fill: colorOf(name, index),
                  stroke: surface,
                  strokeWidth: 2,
                }}
                activeDot={{ r: 5 }}
                connectNulls
                isAnimationActive={false}
              >
                {labels ? (
                  <LabelList
                    dataKey={name}
                    position="top"
                    formatter={tickFmt}
                    style={{ fontSize: 10, fill: AXIS_INK }}
                  />
                ) : null}
              </Line>
            ))}
          </LineChart>
        );
      case "area":
        return (
          <AreaChart
            data={data}
            margin={{ top: 8, right: 16, bottom: 4, left: 12 }}
          >
            {gridLines}
            {xAxis}
            {yAxis}
            {tooltip}
            {legend}
            {result.series.map((name, index) => (
              <Area
                key={name}
                type="monotone"
                dataKey={name}
                stackId={result.series.length > 1 ? "stack" : undefined}
                stroke={colorOf(name, index)}
                fill={colorOf(name, index)}
                fillOpacity={0.25}
                strokeWidth={2}
                isAnimationActive={false}
              />
            ))}
          </AreaChart>
        );
      case "pie":
      case "donut": {
        const slices = foldSlices(result);
        const total = slices.reduce((sum, s) => sum + Math.max(0, s.value), 0);
        return (
          <PieChart>
            {tooltip}
            {showLegend ? (
              <Legend wrapperStyle={{ fontSize: 12 }} iconType="circle" />
            ) : null}
            <Pie
              data={slices}
              dataKey="value"
              nameKey="name"
              innerRadius={chartType === "donut" ? "55%" : 0}
              outerRadius="80%"
              paddingAngle={1}
              stroke={surface}
              strokeWidth={2}
              isAnimationActive={false}
              label={
                labels
                  ? ({ name, value }: { name?: string; value?: number }) =>
                      `${name}: ${total ? ((Number(value) / total) * 100).toFixed(0) : 0}%`
                  : false
              }
            >
              {slices.map((slice, index) => (
                <Cell
                  key={slice.name}
                  fill={seriesColor(index, slice.name, mode)}
                />
              ))}
            </Pie>
            {chartType === "donut" ? (
              <text
                x="50%"
                y="50%"
                textAnchor="middle"
                dominantBaseline="middle"
                style={{ fontSize: 18, fontWeight: 600, fill: "currentColor" }}
              >
                {formatNumber(total, format === "percent" ? "compact" : format)}
              </text>
            ) : null}
          </PieChart>
        );
      }
      case "treemap": {
        const values = data.map((d) => Math.max(0, Number(d[VALUE] ?? 0)));
        const positive = values.filter((v) => v > 0);
        const max = Math.max(...positive, 0);
        // Shade across the values present, not from zero: 1.2M–1.7M from
        // zero all land at the dark end and the tiles look the same.
        const min = positive.length > 1 ? Math.min(...positive) : 0;
        const cells = data
          .map((d, i) => ({ name: String(d.category), size: values[i] }))
          .filter((c) => c.size > 0);
        return (
          <Treemap
            data={cells}
            dataKey="size"
            nameKey="name"
            stroke={surface}
            isAnimationActive={false}
            content={
              <TreemapCell
                min={min}
                max={max}
                labels
                format={(v) => tickFmt(v)}
              />
            }
          >
            {tooltip}
          </Treemap>
        );
      }
      case "waterfall": {
        const steps = waterfall(result);
        const total = steps.reduce((sum, s) => sum + s.value, 0);
        const rows = [
          ...steps,
          {
            category: "Total",
            base: Math.min(0, total),
            rise: Math.max(0, total),
            fall: Math.max(0, -total),
            value: total,
            isTotal: true,
          },
        ];
        return (
          <BarChart
            data={rows}
            barCategoryGap="15%"
            margin={{ top: 8, right: 16, bottom: 4, left: 12 }}
          >
            {gridLines}
            {xAxis}
            {yAxis}
            <Tooltip
              formatter={(_v, name, item) =>
                name === "base"
                  ? null
                  : fmt((item.payload as { value: number }).value)
              }
              contentStyle={{
                background: "var(--popover)",
                color: "var(--popover-foreground)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                fontSize: 12,
              }}
            />
            <Bar
              dataKey="base"
              stackId="w"
              fill="transparent"
              isAnimationActive={false}
              legendType="none"
            />
            <Bar
              dataKey="rise"
              name="Increase"
              stackId="w"
              fill={DIVERGING.positive}
              isAnimationActive={false}
            >
              {rows.map((row) => (
                <Cell
                  key={row.category}
                  fill={"isTotal" in row ? MUTED[mode] : DIVERGING.positive}
                />
              ))}
            </Bar>
            <Bar
              dataKey="fall"
              name="Decrease"
              stackId="w"
              fill={DIVERGING.negative}
              isAnimationActive={false}
            >
              {rows.map((row) => (
                <Cell
                  key={row.category}
                  fill={"isTotal" in row ? MUTED[mode] : DIVERGING.negative}
                />
              ))}
            </Bar>
          </BarChart>
        );
      }
      default:
        return null;
    }
  }

  const htmlView =
    chartType === "kpi" ? (
      <KpiView
        result={result}
        axis={axis}
        fmt={(v) => formatNumber(v, format === "percent" ? "auto" : format)}
      />
    ) : chartType === "heatmap" ? (
      effectiveSeries ? (
        <MatrixView
          result={result}
          axis={axis}
          legend={effectiveSeries}
          fmt={fmt}
          heat
          mode={mode}
        />
      ) : (
        <p className="py-10 text-center text-sm text-muted-foreground">
          A heatmap needs two dimensions. Choose a Legend dimension.
        </p>
      )
    ) : chartType === "matrix" ? (
      <MatrixView
        result={result}
        axis={axis}
        legend={effectiveSeries ?? VALUE}
        fmt={fmt}
        mode={mode}
      />
    ) : null;

  const dimensionChoices = table.dimensions.map((d) => ({
    value: d,
    label: d,
  }));

  return (
    <div className="space-y-4" data-testid="viz-builder">
      <div className="flex flex-wrap items-end gap-3 rounded-md border p-3">
        <Picker
          id="viz-type"
          label="Visual"
          value={chartType}
          width="w-44"
          choices={CHART_TYPES.map((t) => ({ value: t.value, label: t.label }))}
          onChange={(v) => setChartType(v as ChartType)}
        />
        <Picker
          id="viz-axis"
          label="Axis"
          value={axis}
          choices={dimensionChoices}
          onChange={(v) => {
            setAxis(v);
            if (series === v) setSeries(null);
            setFilters((current) => without(current, v));
          }}
        />
        {/* One value per category: no legend to choose. The dimension it
            held becomes a slicer instead. */}
        {singleSeries ? null : (
          <Picker
            id="viz-legend"
            label="Legend"
            value={series ?? NONE}
            choices={[
              { value: NONE, label: "None" },
              ...dimensionChoices.filter((c) => c.value !== axis),
            ]}
            onChange={(v) => {
              const next = v === NONE ? null : v;
              setSeries(next);
              if (next) setFilters((current) => without(current, next));
            }}
          />
        )}
        {slicerDims.map((dimension) => (
          <Picker
            key={dimension}
            id={`viz-slicer-${dimension}`}
            label={`Slicer: ${dimension}`}
            value={filters[dimension] ?? ALL}
            choices={[
              { value: ALL, label: "All (summed)" },
              ...membersOf(table, dimension).map((m) => ({
                value: m,
                label: m,
              })),
            ]}
            onChange={(v) =>
              setFilters((current) => {
                const next = { ...current };
                if (v === ALL) delete next[dimension];
                else next[dimension] = v;
                return next;
              })
            }
          />
        ))}
        <Picker
          id="viz-sort"
          label="Sort"
          value={sort}
          width="w-36"
          choices={SORTS}
          onChange={(v) => setSort(v as SortOrder)}
        />
        <Picker
          id="viz-top"
          label="Show"
          value={topN}
          width="w-28"
          choices={TOP_N.map((n) => ({
            value: n,
            label: n === "all" ? "All" : `Top ${n}`,
          }))}
          onChange={(v) => setTopN(v as (typeof TOP_N)[number])}
        />
        <Picker
          id="viz-format"
          label="Numbers"
          value={format}
          width="w-36"
          choices={FORMATS}
          onChange={(v) => setFormat(v as NumberFormat)}
        />
        <Picker
          id="viz-size"
          label="Size"
          value={height}
          width="w-28"
          choices={[
            { value: "small", label: "Small" },
            { value: "medium", label: "Medium" },
            { value: "large", label: "Large" },
          ]}
          onChange={(v) => setHeight(v as HeightKey)}
        />
        {/* Chart styling only means something on a drawn chart; the
            table-style views (KPI, matrix, heatmap) have none. */}
        {SVG_TYPES.includes(chartType) ? (
          <div className="flex flex-wrap items-center gap-3 pb-2">
            {chartType !== "treemap" ? (
              <Toggle
                id="viz-labels"
                label="Data labels"
                checked={labels}
                onChange={setLabels}
              />
            ) : null}
            {["treemap", "waterfall"].includes(chartType) ? null : (
              <Toggle
                id="viz-legend-toggle"
                label="Legend"
                checked={showLegend}
                onChange={setShowLegend}
              />
            )}
            {["pie", "donut", "treemap"].includes(chartType) ? null : (
              <Toggle
                id="viz-grid"
                label="Gridlines"
                checked={grid}
                onChange={setGrid}
              />
            )}
          </div>
        ) : null}
      </div>

      <p className="text-xs text-muted-foreground">
        {CHART_TYPES.find((t) => t.value === chartType)?.help}
      </p>

      <div
        ref={chartRef}
        className="w-full"
        style={htmlView ? undefined : { height: HEIGHTS[height] }}
      >
        {htmlView ?? (
          <ResponsiveContainer width="100%" height="100%">
            {body ?? <div />}
          </ResponsiveContainer>
        )}
      </div>

      {notes.length ? (
        <ul className="space-y-0.5 text-xs text-muted-foreground">
          {notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}

      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() =>
            download(
              `${safeName(title)}.csv`,
              pivotToCsv(result, axis),
              "text/csv",
            )
          }
        >
          <Download className="mr-2 h-3.5 w-3.5" />
          Export view (CSV)
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() =>
            download(
              `${safeName(title)}-cells.csv`,
              tableToCsv(table),
              "text/csv",
            )
          }
        >
          <Download className="mr-2 h-3.5 w-3.5" />
          Export all cells (CSV)
        </Button>
        {SVG_TYPES.includes(chartType) ? (
          <Button size="sm" variant="outline" onClick={exportPng}>
            <ImageDown className="mr-2 h-3.5 w-3.5" />
            Save image (PNG)
          </Button>
        ) : null}
      </div>

      {chartType !== "matrix" ? (
        <details className="rounded-md border">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
            Table view
          </summary>
          <div className="border-t p-2">
            <MatrixView
              result={result}
              axis={axis}
              legend={effectiveSeries ?? VALUE}
              fmt={fmt}
              mode={mode}
            />
          </div>
        </details>
      ) : null}
    </div>
  );
}

/** A slicer on a dimension that just became the axis or legend no longer applies. */
function without(
  filters: Record<string, string>,
  dimension: string,
): Record<string, string> {
  const next = { ...filters };
  delete next[dimension];
  return next;
}

function foldSlices(result: PivotResult) {
  const slices = result.data
    .map((d) => ({ name: String(d.category), value: Number(d[VALUE] ?? 0) }))
    .filter((s) => s.value > 0)
    .sort((a, b) => b.value - a.value);
  if (slices.length <= 8) return slices;
  const rest = slices.slice(7).reduce((sum, s) => sum + s.value, 0);
  return [...slices.slice(0, 7), { name: OTHER, value: rest }];
}

function TreemapCell(props: {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  name?: string;
  size?: number;
  min: number;
  max: number;
  labels: boolean;
  format: (v: number) => string;
}) {
  const {
    x = 0,
    y = 0,
    width = 0,
    height = 0,
    name = "",
    size = 0,
    min,
    max,
    format,
  } = props;
  // Shade from a step above the lightest, so the smallest tile is still
  // visibly a tile against the surface.
  const fill = sequentialColor(size, min - (max - min) * 0.25, max);
  const room = width > 60 && height > 28;
  return (
    <g>
      <rect x={x} y={y} width={width} height={height} fill={fill} rx={4} />
      {room ? (
        // stroke="none": the treemap's tile border otherwise outlines the text.
        <text
          x={x + 6}
          y={y + 16}
          fill={inkOn(fill)}
          stroke="none"
          style={{ fontSize: 11 }}
        >
          {name.length > width / 7
            ? `${name.slice(0, Math.max(3, Math.floor(width / 7) - 1))}…`
            : name}
          <tspan x={x + 6} dy={14}>
            {format(size)}
          </tspan>
        </text>
      ) : null}
    </g>
  );
}

function KpiView({
  result,
  axis,
  fmt,
}: {
  result: PivotResult;
  axis: string;
  fmt: (v: number) => string;
}) {
  const values = result.data.map((d) => ({
    name: String(d.category),
    value: Number(d[VALUE] ?? 0),
  }));
  if (!values.length)
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        No numeric values for this selection.
      </p>
    );
  const total = values.reduce((sum, v) => sum + v.value, 0);
  const highest = values.reduce((a, b) => (b.value > a.value ? b : a));
  const lowest = values.reduce((a, b) => (b.value < a.value ? b : a));
  const tiles = [
    {
      label: "Total",
      value: fmt(total),
      detail: `${values.length} ${axis} member(s)`,
    },
    {
      label: "Average",
      value: fmt(total / values.length),
      detail: `per ${axis}`,
    },
    { label: "Highest", value: fmt(highest.value), detail: highest.name },
    { label: "Lowest", value: fmt(lowest.value), detail: lowest.name },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {tiles.map((tile) => (
        <div key={tile.label} className="rounded-lg border p-4">
          <p className="text-xs text-muted-foreground">{tile.label}</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums">
            {tile.value}
          </p>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {tile.detail}
          </p>
        </div>
      ))}
    </div>
  );
}

function MatrixView({
  result,
  axis,
  legend,
  fmt,
  heat = false,
  mode,
}: {
  result: PivotResult;
  axis: string;
  legend: string;
  fmt: (v: unknown) => string;
  heat?: boolean;
  mode: Mode;
}) {
  const values = result.data.flatMap((d) =>
    result.series
      .map((s) => d[s])
      .filter((v): v is number => typeof v === "number"),
  );
  const min = Math.min(...values);
  const max = Math.max(...values);
  const columnTotals = result.series.map((s) =>
    result.data.reduce(
      (sum, d) => sum + ((d[s] as number | undefined) ?? 0),
      0,
    ),
  );
  const showTotals = result.series.length > 1;

  return (
    <div className="max-h-[480px] overflow-auto">
      <table className="w-full border-collapse text-xs">
        <thead className="sticky top-0 bg-background">
          <tr>
            <th className="border-b px-2 py-1.5 text-left font-medium">
              {axis}
              {legend !== VALUE ? (
                <span className="text-muted-foreground"> / {legend}</span>
              ) : null}
            </th>
            {result.series.map((s) => (
              <th
                key={s}
                className="border-b px-2 py-1.5 text-right font-medium"
              >
                {s}
              </th>
            ))}
            {showTotals ? (
              <th className="border-b px-2 py-1.5 text-right font-medium">
                Total
              </th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {result.data.map((row) => {
            const total = result.series.reduce(
              (sum, s) => sum + ((row[s] as number | undefined) ?? 0),
              0,
            );
            return (
              <tr key={String(row.category)} className="border-b last:border-0">
                <td className="px-2 py-1 font-medium">
                  {String(row.category)}
                </td>
                {result.series.map((s) => {
                  const value = row[s];
                  const fill =
                    heat && typeof value === "number"
                      ? sequentialColor(value, min, max)
                      : undefined;
                  return (
                    <td
                      key={s}
                      className="px-2 py-1 text-right tabular-nums"
                      style={
                        fill
                          ? { background: fill, color: inkOn(fill) }
                          : undefined
                      }
                    >
                      {value === undefined ? "" : fmt(value)}
                    </td>
                  );
                })}
                {showTotals ? (
                  <td className="px-2 py-1 text-right font-medium tabular-nums">
                    {fmt(total)}
                  </td>
                ) : null}
              </tr>
            );
          })}
        </tbody>
        {showTotals ? (
          <tfoot>
            <tr className="border-t-2">
              <td className="px-2 py-1 font-semibold">Total</td>
              {columnTotals.map((total, index) => (
                <td
                  key={result.series[index]}
                  className="px-2 py-1 text-right font-semibold tabular-nums"
                >
                  {fmt(total)}
                </td>
              ))}
              <td className="px-2 py-1 text-right font-semibold tabular-nums">
                {fmt(columnTotals.reduce((a, b) => a + b, 0))}
              </td>
            </tr>
          </tfoot>
        ) : null}
      </table>
      {heat ? (
        <p
          className="mt-2 text-xs text-muted-foreground"
          style={{ color: mode === "dark" ? "#c3c2b7" : undefined }}
        >
          Darker is higher. Low {fmt(min)} · high {fmt(max)}.
        </p>
      ) : null}
    </div>
  );
}
