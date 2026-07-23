"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { BarChart3, Loader2, Sparkles } from "lucide-react";
import { useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, apiRequest } from "@/lib/api-client";
import type { TM1Connection, VisualizeResponseBody } from "@/lib/types";

// Charts beyond this many bars stop being readable — fall back to the table
// only rather than rendering an unreadable wall of bars.
const MAX_CHART_BARS = 30;

type ChartKind = "bar" | "line" | "area";

const CHART_HEIGHTS = {
  small: 240,
  medium: 320,
  large: 480,
} as const;

type ChartHeightKey = keyof typeof CHART_HEIGHTS;

const DEFAULT_CHART_COLOR = "#1877f2";

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong.";
}

export default function VisualizePage() {
  const [connectionId, setConnectionId] = useState<string>("");
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<VisualizeResponseBody | null>(null);
  const [chartKind, setChartKind] = useState<ChartKind>("bar");
  const [chartColor, setChartColor] = useState(DEFAULT_CHART_COLOR);
  const [chartHeightKey, setChartHeightKey] = useState<ChartHeightKey>("medium");

  const connectionsQuery = useQuery({
    queryKey: ["tm1-connections"],
    queryFn: () => apiRequest<TM1Connection[]>("/tm1/connections"),
  });

  const visualizeMutation = useMutation({
    mutationFn: () =>
      apiRequest<VisualizeResponseBody>(
        `/tm1/connections/${connectionId}/visualize`,
        { method: "POST", body: { query } },
      ),
    onSuccess: (data) => setResult(data),
    onError: (error) => toast.error(errorMessage(error)),
  });

  const chartData = result?.cells.slice(0, MAX_CHART_BARS) ?? [];
  const showChart = chartData.length > 0 && chartData.length <= MAX_CHART_BARS;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Visualize</h1>
        <p className="text-sm text-muted-foreground">
          Ask a data question in plain language — the Analyst agent finds the
          right cube, confirms real element names, and runs the MDX for you.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Ask a data question</CardTitle>
          <CardDescription>
            e.g. &quot;Show me revenue by month for 2026&quot; — results are
            capped at 500 cells; narrow the question (a specific period,
            account, or entity) for a cleaner chart.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-2">
            <div className="flex-1 space-y-2">
              <Textarea
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Show me revenue by month for 2026"
                rows={3}
              />
            </div>
            <Select
              value={connectionId}
              onValueChange={(value) => setConnectionId(value ?? "")}
            >
              <SelectTrigger className="w-56" aria-label="Connection">
                <SelectValue placeholder="Select connection" />
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
          <Button
            onClick={() => visualizeMutation.mutate()}
            disabled={
              visualizeMutation.isPending || !query.trim() || !connectionId
            }
          >
            {visualizeMutation.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="mr-2 h-4 w-4" />
            )}
            Visualize
          </Button>
        </CardContent>
      </Card>

      {result ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <BarChart3 className="h-4 w-4" />
              {result.cube_name || "Results"}
            </CardTitle>
            <CardDescription>{result.summary}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">
              {result.mdx}
            </pre>

            {result.cells.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                The query ran successfully but returned no cells.
              </p>
            ) : (
              <>
                {showChart ? (
                  <>
                    <div className="flex flex-wrap items-end gap-4 rounded-md border p-3">
                      <div className="space-y-1.5">
                        <Label htmlFor="chart-kind" className="text-xs">
                          Chart type
                        </Label>
                        <Select
                          value={chartKind}
                          onValueChange={(v) => setChartKind((v as ChartKind) ?? "bar")}
                        >
                          <SelectTrigger id="chart-kind" className="w-32" aria-label="Chart type">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="bar">Bar</SelectItem>
                            <SelectItem value="line">Line</SelectItem>
                            <SelectItem value="area">Area</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="chart-size" className="text-xs">
                          Size
                        </Label>
                        <Select
                          value={chartHeightKey}
                          onValueChange={(v) =>
                            setChartHeightKey((v as ChartHeightKey) ?? "medium")
                          }
                        >
                          <SelectTrigger id="chart-size" className="w-28" aria-label="Chart size">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="small">Small</SelectItem>
                            <SelectItem value="medium">Medium</SelectItem>
                            <SelectItem value="large">Large</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="chart-color" className="text-xs">
                          Color
                        </Label>
                        <input
                          id="chart-color"
                          type="color"
                          value={chartColor}
                          onChange={(e) => setChartColor(e.target.value)}
                          aria-label="Chart color"
                          className="h-9 w-14 cursor-pointer rounded-md border border-input bg-transparent p-1"
                        />
                      </div>
                    </div>

                    <div
                      className="w-full"
                      style={{ height: CHART_HEIGHTS[chartHeightKey] }}
                    >
                      <ResponsiveContainer width="100%" height="100%">
                        {chartKind === "bar" ? (
                          <BarChart data={chartData}>
                            <CartesianGrid strokeDasharray="3 3" />
                            <XAxis
                              dataKey="label"
                              angle={-30}
                              textAnchor="end"
                              height={70}
                              tick={{ fontSize: 11 }}
                            />
                            <YAxis tick={{ fontSize: 11 }} />
                            <Tooltip />
                            <Bar dataKey="value" fill={chartColor} />
                          </BarChart>
                        ) : chartKind === "line" ? (
                          <LineChart data={chartData}>
                            <CartesianGrid strokeDasharray="3 3" />
                            <XAxis
                              dataKey="label"
                              angle={-30}
                              textAnchor="end"
                              height={70}
                              tick={{ fontSize: 11 }}
                            />
                            <YAxis tick={{ fontSize: 11 }} />
                            <Tooltip />
                            <Line
                              type="monotone"
                              dataKey="value"
                              stroke={chartColor}
                              strokeWidth={2}
                              dot={{ fill: chartColor }}
                            />
                          </LineChart>
                        ) : (
                          <AreaChart data={chartData}>
                            <CartesianGrid strokeDasharray="3 3" />
                            <XAxis
                              dataKey="label"
                              angle={-30}
                              textAnchor="end"
                              height={70}
                              tick={{ fontSize: 11 }}
                            />
                            <YAxis tick={{ fontSize: 11 }} />
                            <Tooltip />
                            <Area
                              type="monotone"
                              dataKey="value"
                              fill={chartColor}
                              stroke={chartColor}
                              fillOpacity={0.3}
                            />
                          </AreaChart>
                        )}
                      </ResponsiveContainer>
                    </div>
                  </>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    Too many cells ({result.cells.length}) for a readable
                    chart — showing the table only.
                  </p>
                )}

                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Label</TableHead>
                      <TableHead className="text-right">Value</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {result.cells.map((cell) => (
                      <TableRow key={cell.label}>
                        <TableCell className="font-mono text-xs">
                          {cell.label}
                        </TableCell>
                        <TableCell className="text-right">
                          {cell.value.toLocaleString()}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </>
            )}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
