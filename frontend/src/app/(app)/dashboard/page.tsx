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
import { apiRequest } from "@/lib/api-client";
import type {
  TM1Connection,
  TM1ConnectionStatus,
  ToolUsage,
  UsageSummary,
} from "@/lib/types";

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

export default function DashboardPage() {
  const connectionsQuery = useQuery({
    queryKey: ["tm1-connections"],
    queryFn: () => apiRequest<TM1Connection[]>("/tm1/connections"),
  });

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

  const toolCallTotal = toolsQuery.data?.reduce((sum, t) => sum + t.total_calls, 0) ?? 0;
  const toolErrorTotal = toolsQuery.data?.reduce((sum, t) => sum + t.error_count, 0) ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          Live overview of TM1 connections, AI usage, and platform health.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>TM1 Connections</CardDescription>
            <CardTitle className="text-3xl">
              {connectionsQuery.isPending ? (
                <Skeleton className="h-8 w-12" />
              ) : (
                connectionsQuery.data?.length ?? 0
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            {connectionsQuery.isError
              ? "Failed to load connections."
              : connectionsQuery.isPending
                ? "Loading..."
                : connectionsQuery.data?.length
                  ? `${connectionsQuery.data.filter((c) => c.is_active).length} active`
                  : "No TM1 connections yet."}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardDescription>AI Usage (30 days)</CardDescription>
            <CardTitle className="text-3xl">
              {usageQuery.isPending ? (
                <Skeleton className="h-8 w-16" />
              ) : (
                number.format(usageQuery.data?.total_requests ?? 0)
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            {usageQuery.isError
              ? "Failed to load usage."
              : usageQuery.isPending
                ? "Loading..."
                : usageQuery.data && usageQuery.data.total_requests > 0
                  ? `${number.format(usageQuery.data.total_tokens)} tokens · ${currency.format(usageQuery.data.total_cost_usd)}`
                  : "No AI activity in the last 30 days."}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Tool Executions (30 days)</CardDescription>
            <CardTitle className="text-3xl">
              {toolsQuery.isPending ? (
                <Skeleton className="h-8 w-12" />
              ) : (
                number.format(toolCallTotal)
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            {toolsQuery.isError
              ? "Failed to load tool executions."
              : toolsQuery.isPending
                ? "Loading..."
                : toolCallTotal > 0
                  ? `${toolErrorTotal} error${toolErrorTotal === 1 ? "" : "s"}`
                  : "No tool executions in the last 30 days."}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Circuit Breakers</CardDescription>
            <CardTitle className="text-3xl">
              {tm1StatusQuery.isPending ? (
                <Skeleton className="h-8 w-12" />
              ) : (
                tm1StatusQuery.data?.length ?? 0
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            {tm1StatusQuery.isError
              ? "Failed to load circuit breaker status."
              : tm1StatusQuery.isPending
                ? "Loading..."
                : tm1StatusQuery.data?.length
                  ? `${tm1StatusQuery.data.filter((s) => s.state === "closed").length} healthy`
                  : "No TM1 connections to monitor yet."}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>TM1 Connection Status</CardTitle>
          <CardDescription>
            Circuit breaker state per connection, read live from the backend.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {tm1StatusQuery.isError ? (
            <p className="text-sm text-destructive">
              Failed to load circuit breaker status.
            </p>
          ) : tm1StatusQuery.isPending ? (
            <div className="space-y-2">
              <Skeleton className="h-6 w-full" />
              <Skeleton className="h-6 w-full" />
            </div>
          ) : tm1StatusQuery.data?.length ? (
            <ul className="divide-y">
              {tm1StatusQuery.data.map((status) => (
                <li
                  key={status.connection_id}
                  className="flex items-center justify-between py-2 text-sm"
                >
                  <span>{status.name}</span>
                  <div className="flex items-center gap-3">
                    {status.failure_count > 0 ? (
                      <span className="text-muted-foreground">
                        {status.failure_count} failure
                        {status.failure_count === 1 ? "" : "s"}
                      </span>
                    ) : null}
                    <Badge variant={STATE_VARIANT[status.state]}>
                      {status.state.replace("_", " ")}
                    </Badge>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">
              No TM1 connections yet — connections will appear here once
              they&apos;re created.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
