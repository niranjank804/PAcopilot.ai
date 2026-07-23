"use client";

import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, apiRequest } from "@/lib/api-client";
import type { TM1ConnectionStatus, ToolUsage, UsageSummary } from "@/lib/types";

const currency = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

const number = new Intl.NumberFormat("en-US");

const STATE_VARIANT: Record<TM1ConnectionStatus["state"], "default" | "secondary" | "destructive"> = {
  closed: "default",
  half_open: "secondary",
  open: "destructive",
};

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong.";
}

export default function MonitoringPage() {
  const usageQuery = useQuery({
    queryKey: ["monitoring-usage"],
    queryFn: () => apiRequest<UsageSummary>("/monitoring/usage?days=30"),
  });

  const toolsQuery = useQuery({
    queryKey: ["monitoring-tools"],
    queryFn: () => apiRequest<ToolUsage[]>("/monitoring/tools?days=30"),
  });

  const tm1StatusQuery = useQuery({
    queryKey: ["monitoring-tm1-status"],
    queryFn: () => apiRequest<TM1ConnectionStatus[]>("/monitoring/tm1-status"),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Monitoring</h1>
        <p className="text-sm text-muted-foreground">
          AI usage, tool execution health, and TM1 circuit breaker state over
          the last 30 days.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>AI Usage by Model</CardTitle>
          <CardDescription>
            {usageQuery.data
              ? `${number.format(usageQuery.data.total_requests)} requests · ${number.format(usageQuery.data.total_tokens)} tokens · ${currency.format(usageQuery.data.total_cost_usd)} total`
              : "Token and cost totals per model."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {usageQuery.isError ? (
            <p className="py-6 text-center text-sm text-destructive">
              Failed to load usage: {errorMessage(usageQuery.error)}
            </p>
          ) : usageQuery.isPending ? (
            <Skeleton className="h-24 w-full" />
          ) : !usageQuery.data?.by_model.length ? (
            <p className="py-10 text-center text-sm text-muted-foreground">
              No AI activity in the last 30 days.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Model</TableHead>
                  <TableHead className="text-right">Requests</TableHead>
                  <TableHead className="text-right">Tokens</TableHead>
                  <TableHead className="text-right">Cost</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {usageQuery.data.by_model.map((row) => (
                  <TableRow key={row.model}>
                    <TableCell className="font-medium">{row.model}</TableCell>
                    <TableCell className="text-right">
                      {number.format(row.requests)}
                    </TableCell>
                    <TableCell className="text-right">
                      {number.format(row.total_tokens)}
                    </TableCell>
                    <TableCell className="text-right">
                      {currency.format(row.total_cost_usd)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Tool Executions</CardTitle>
          <CardDescription>
            AI tool calls against TM1 metadata, by tool.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {toolsQuery.isError ? (
            <p className="py-6 text-center text-sm text-destructive">
              Failed to load tool executions: {errorMessage(toolsQuery.error)}
            </p>
          ) : toolsQuery.isPending ? (
            <Skeleton className="h-24 w-full" />
          ) : !toolsQuery.data?.length ? (
            <p className="py-10 text-center text-sm text-muted-foreground">
              No tool executions in the last 30 days.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Tool</TableHead>
                  <TableHead className="text-right">Calls</TableHead>
                  <TableHead className="text-right">Succeeded</TableHead>
                  <TableHead className="text-right">Errors</TableHead>
                  <TableHead className="text-right">Avg duration</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {toolsQuery.data.map((row) => (
                  <TableRow key={row.tool_name}>
                    <TableCell className="font-medium">
                      {row.tool_name}
                    </TableCell>
                    <TableCell className="text-right">
                      {number.format(row.total_calls)}
                    </TableCell>
                    <TableCell className="text-right">
                      {number.format(row.success_count)}
                    </TableCell>
                    <TableCell className="text-right">
                      {row.error_count > 0 ? (
                        <span className="text-destructive">
                          {number.format(row.error_count)}
                        </span>
                      ) : (
                        "0"
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      {Math.round(row.avg_duration_ms)} ms
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>TM1 Circuit Breakers</CardTitle>
          <CardDescription>
            Live resilience state per TM1 connection.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {tm1StatusQuery.isError ? (
            <p className="py-6 text-center text-sm text-destructive">
              Failed to load circuit breaker status:{" "}
              {errorMessage(tm1StatusQuery.error)}
            </p>
          ) : tm1StatusQuery.isPending ? (
            <Skeleton className="h-24 w-full" />
          ) : !tm1StatusQuery.data?.length ? (
            <p className="py-10 text-center text-sm text-muted-foreground">
              No TM1 connections to monitor yet.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Connection</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead className="text-right">Failure count</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {tm1StatusQuery.data.map((row) => (
                  <TableRow key={row.connection_id}>
                    <TableCell className="font-medium">{row.name}</TableCell>
                    <TableCell>
                      <Badge variant={STATE_VARIANT[row.state]}>
                        {row.state.replace("_", " ")}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      {row.failure_count}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
