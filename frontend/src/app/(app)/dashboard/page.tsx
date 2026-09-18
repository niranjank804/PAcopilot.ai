"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Coins,
  Database,
  MessageSquare,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { KpiCard } from "@/components/ui/kpi-card";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { apiRequest } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import type {
  ConversationSummary,
  TM1Connection,
  TM1ConnectionStatus,
  ToolUsage,
  UsageSummary,
} from "@/lib/types";

const number = new Intl.NumberFormat("en-US");
const percent = new Intl.NumberFormat("en-US", {
  style: "percent",
  maximumFractionDigits: 1,
});
const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

/** A breaker that has tripped is a problem; half-open is recovering. */
const STATE_VARIANT: Record<
  TM1ConnectionStatus["state"],
  "success" | "warning" | "destructive"
> = {
  closed: "success",
  half_open: "warning",
  open: "destructive",
};

const STATE_LABEL: Record<TM1ConnectionStatus["state"], string> = {
  closed: "healthy",
  half_open: "recovering",
  open: "unavailable",
};

function greeting(date: Date): string {
  const hour = date.getHours();

  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";

  return "Good evening";
}

/** "4 minutes ago" — the unit a control room reads in. */
function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();

  if (Number.isNaN(then)) return "";

  const minutes = Math.round((Date.now() - then) / 60_000);

  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;

  const hours = Math.round(minutes / 60);

  if (hours < 24) return `${hours} h ago`;

  const days = Math.round(hours / 24);

  return days === 1 ? "yesterday" : `${days} days ago`;
}

export default function DashboardPage() {
  const { user } = useAuth();

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

  const conversationsQuery = useQuery({
    queryKey: ["ai-conversations"],
    queryFn: () => apiRequest<ConversationSummary[]>("/ai/conversations"),
  });

  const toolCallTotal =
    toolsQuery.data?.reduce((sum, tool) => sum + tool.total_calls, 0) ?? 0;
  const toolErrorTotal =
    toolsQuery.data?.reduce((sum, tool) => sum + tool.error_count, 0) ?? 0;
  const successRate =
    toolCallTotal > 0 ? (toolCallTotal - toolErrorTotal) / toolCallTotal : null;

  const unhealthy =
    tm1StatusQuery.data?.filter((status) => status.state !== "closed") ?? [];

  return (
    <div className="space-y-8">
      <PageHeader
        title={`${greeting(new Date())}${user ? `, ${user.first_name}` : ""}`}
        description="Planning Analytics environment overview — the last 30 days."
        actions={
          <Link href="/chat" className={buttonVariants({ size: "lg" })}>
            <MessageSquare className="size-4" aria-hidden />
            Ask PA Copilot
          </Link>
        }
      />

      {/* Four measurements, each read straight from the monitoring API.
          Nothing here is derived from a target the product does not
          have: there is no quota endpoint, so there is no "% of plan". */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="AI runs"
          help="Every assistant request answered in the last 30 days, across all users in your organization. Read from the same usage log that bills tokens."
          icon={<Activity className="size-4" />}
          value={number.format(usageQuery.data?.total_requests ?? 0)}
          hint={
            usageQuery.data?.total_requests
              ? `${number.format(usageQuery.data.by_model.length)} model${
                  usageQuery.data.by_model.length === 1 ? "" : "s"
                } in use`
              : "No AI activity in the last 30 days"
          }
          isPending={usageQuery.isPending}
          isError={usageQuery.isError}
          errorText="Usage unavailable"
        />

        <KpiCard
          label="Tool success rate"
          help="Of every TM1 tool call the agents made in 30 days, the share that returned a result. A low rate usually means a connection is down or metadata has not been extracted."
          icon={<ShieldCheck className="size-4" />}
          value={successRate === null ? "—" : percent.format(successRate)}
          hint={
            toolCallTotal > 0
              ? `${number.format(toolCallTotal)} tool executions`
              : "No tool executions yet"
          }
          isPending={toolsQuery.isPending}
          isError={toolsQuery.isError}
          errorText="Tool metrics unavailable"
        />

        <KpiCard
          label="Tool errors"
          help="Tool calls that failed in the last 30 days. Monitoring breaks these down per tool, so you can see whether it is one tool or one server."
          icon={<TriangleAlert className="size-4" />}
          value={number.format(toolErrorTotal)}
          hint={
            toolErrorTotal > 0
              ? "Investigate in Monitoring"
              : "No failed tool calls"
          }
          isPending={toolsQuery.isPending}
          isError={toolsQuery.isError}
          errorText="Tool metrics unavailable"
        />

        <KpiCard
          label="Tokens"
          help="Input and output tokens sent to the model in 30 days. The cost is estimated from list prices; cached prompt tokens are billed at a tenth, which is what the cached share shows."
          icon={<Coins className="size-4" />}
          value={number.format(usageQuery.data?.total_tokens ?? 0)}
          hint={
            usageQuery.data
              ? `${money.format(usageQuery.data.total_cost_usd)} estimated · ${percent.format(
                  usageQuery.data.cache_hit_rate,
                )} cached`
              : undefined
          }
          isPending={usageQuery.isPending}
          isError={usageQuery.isError}
          errorText="Usage unavailable"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader className="border-b pb-4">
            <CardTitle className="text-card-title">Recent AI activity</CardTitle>
            <CardDescription>
              Your latest assistant sessions, newest first.
            </CardDescription>
          </CardHeader>
          <CardContent className="px-0">
            {conversationsQuery.isError ? (
              <p className="px-6 text-sm text-destructive">
                Failed to load recent activity.
              </p>
            ) : conversationsQuery.isPending ? (
              <div className="space-y-2 px-6">
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            ) : conversationsQuery.data?.length ? (
              <ul className="divide-y divide-border">
                {conversationsQuery.data.slice(0, 6).map((conversation) => (
                  <li key={conversation.id}>
                    <Link
                      href={`/chat?conversation=${conversation.id}`}
                      className="flex items-center justify-between gap-4 px-6 py-3 transition-colors hover:bg-secondary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <span className="min-w-0 truncate text-sm text-foreground">
                        {conversation.title ?? "Untitled session"}
                      </span>
                      <span className="shrink-0 text-xs text-tertiary-foreground">
                        {relativeTime(conversation.updated_at)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                icon={<MessageSquare className="size-4" />}
                title="No AI sessions yet"
                description="Ask the assistant about a cube, a rule or a TurboIntegrator process to get started."
                action={
                  <Link
                    href="/chat"
                    className={buttonVariants({ variant: "outline", size: "sm" })}
                  >
                    Open AI Assistant
                  </Link>
                }
              />
            )}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader className="border-b pb-4">
            <CardTitle className="text-card-title">TM1 connections</CardTitle>
            <CardDescription>
              {connectionsQuery.data?.length
                ? `${connectionsQuery.data.filter((c) => c.is_active).length} of ${
                    connectionsQuery.data.length
                  } active · circuit breaker state`
                : "Circuit breaker state per connection."}
            </CardDescription>
          </CardHeader>
          <CardContent className="px-0">
            {tm1StatusQuery.isError ? (
              <p className="px-6 text-sm text-destructive">
                Failed to load circuit breaker status.
              </p>
            ) : tm1StatusQuery.isPending ? (
              <div className="space-y-2 px-6">
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-full" />
              </div>
            ) : tm1StatusQuery.data?.length ? (
              <ul className="divide-y divide-border">
                {tm1StatusQuery.data.map((status) => (
                  <li
                    key={status.connection_id}
                    className="flex items-center justify-between gap-3 px-6 py-3"
                  >
                    <span className="min-w-0 truncate text-sm">{status.name}</span>
                    <div className="flex shrink-0 items-center gap-3">
                      {status.failure_count > 0 ? (
                        <span className="text-xs text-tertiary-foreground">
                          {status.failure_count} failure
                          {status.failure_count === 1 ? "" : "s"}
                        </span>
                      ) : null}
                      <Badge variant={STATE_VARIANT[status.state]}>
                        {STATE_LABEL[status.state]}
                      </Badge>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                icon={<Database className="size-4" />}
                title="No TM1 connections"
                description="Connect a Planning Analytics server to explore cubes, rules and processes."
                action={
                  <Link
                    href="/connections"
                    className={buttonVariants({ variant: "outline", size: "sm" })}
                  >
                    Add a connection
                  </Link>
                }
              />
            )}
          </CardContent>
        </Card>
      </div>

      {unhealthy.length > 0 ? (
        <p className="text-sm text-muted-foreground">
          {unhealthy.length} connection{unhealthy.length === 1 ? "" : "s"} not
          answering normally.{" "}
          <Link href="/monitoring" className="text-primary hover:underline">
            Open Monitoring
          </Link>
        </p>
      ) : null}
    </div>
  );
}
