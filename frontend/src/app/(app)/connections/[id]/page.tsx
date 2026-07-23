"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  Boxes,
  Calendar,
  GitBranch,
  Layers,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { ApiError, apiRequest } from "@/lib/api-client";
import { CHANGE_TYPE_LABEL, STATUS_VARIANT } from "@/lib/change-format";
import type { TM1ChangeSummary, TM1Connection } from "@/lib/types";

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong.";
}

interface NameListProps {
  isPending: boolean;
  isError: boolean;
  error: unknown;
  names: string[] | undefined;
  emptyLabel: string;
}

// The backend's list endpoints return plain name lists (list[str]) — per-item
// detail comes from the per-object endpoints and is deliberately not fetched
// here (it would be one live TM1 call per object).
function NameList({ isPending, isError, error, names, emptyLabel }: NameListProps) {
  // isError first: isPending stays true while v5 retries, but once the query
  // settles with an error we must never fall through to the empty state.
  if (isError) {
    return (
      <p className="py-6 text-center text-sm text-destructive">
        Failed to load: {errorMessage(error)}
      </p>
    );
  }

  if (isPending) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
      </div>
    );
  }

  if (!names?.length) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        {emptyLabel}
      </p>
    );
  }

  return (
    <ul className="divide-y">
      {names.map((name) => (
        <li key={name} className="py-2.5 text-sm font-medium">
          {name}
        </li>
      ))}
    </ul>
  );
}

export default function ConnectionDetailPage() {
  const params = useParams<{ id: string }>();
  const connectionId = params.id;

  const connectionQuery = useQuery({
    queryKey: ["tm1-connection", connectionId],
    queryFn: () =>
      apiRequest<TM1Connection>(`/tm1/connections/${connectionId}`),
  });

  const cubesQuery = useQuery({
    queryKey: ["tm1-cubes", connectionId],
    queryFn: () =>
      apiRequest<string[]>(`/tm1/connections/${connectionId}/cubes`),
  });

  const dimensionsQuery = useQuery({
    queryKey: ["tm1-dimensions", connectionId],
    queryFn: () =>
      apiRequest<string[]>(`/tm1/connections/${connectionId}/dimensions`),
  });

  const processesQuery = useQuery({
    queryKey: ["tm1-processes", connectionId],
    queryFn: () =>
      apiRequest<string[]>(`/tm1/connections/${connectionId}/processes`),
  });

  const choresQuery = useQuery({
    queryKey: ["tm1-chores", connectionId],
    queryFn: () =>
      apiRequest<string[]>(`/tm1/connections/${connectionId}/chores`),
  });

  const changesQuery = useQuery({
    queryKey: ["tm1-changes", connectionId],
    queryFn: () =>
      apiRequest<TM1ChangeSummary[]>(`/tm1/connections/${connectionId}/changes`),
  });

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/connections"
          className={buttonVariants({
            variant: "ghost",
            size: "sm",
            className: "-ml-2 mb-2",
          })}
        >
          <ArrowLeft className="mr-2 h-4 w-4" />
          All connections
        </Link>
        {connectionQuery.isError ? (
          <p className="text-sm text-destructive">
            Failed to load connection: {errorMessage(connectionQuery.error)}
          </p>
        ) : connectionQuery.isPending ? (
          <Skeleton className="h-8 w-64" />
        ) : (
          <>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-semibold tracking-tight">
                {connectionQuery.data?.name}
              </h1>
              <Badge
                variant={connectionQuery.data?.is_active ? "default" : "secondary"}
              >
                {connectionQuery.data?.is_active ? "active" : "inactive"}
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground">
              {connectionQuery.data?.address}:{connectionQuery.data?.port}
              {connectionQuery.data?.ssl ? " · SSL" : ""} ·{" "}
              {connectionQuery.data?.username}
            </p>
          </>
        )}
      </div>

      <Tabs defaultValue="cubes">
        <TabsList>
          <TabsTrigger value="cubes">
            <Boxes className="mr-2 h-4 w-4" />
            Cubes {cubesQuery.data ? `(${cubesQuery.data.length})` : ""}
          </TabsTrigger>
          <TabsTrigger value="dimensions">
            <Layers className="mr-2 h-4 w-4" />
            Dimensions{" "}
            {dimensionsQuery.data ? `(${dimensionsQuery.data.length})` : ""}
          </TabsTrigger>
          <TabsTrigger value="processes">
            <GitBranch className="mr-2 h-4 w-4" />
            Processes{" "}
            {processesQuery.data ? `(${processesQuery.data.length})` : ""}
          </TabsTrigger>
          <TabsTrigger value="chores">
            <Calendar className="mr-2 h-4 w-4" />
            Chores {choresQuery.data ? `(${choresQuery.data.length})` : ""}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="cubes">
          <Card>
            <CardHeader>
              <CardTitle>Cubes</CardTitle>
              <CardDescription>
                Read live from the TM1 server (control cubes excluded).
              </CardDescription>
            </CardHeader>
            <CardContent>
              <NameList
                isPending={cubesQuery.isPending}
                isError={cubesQuery.isError}
                error={cubesQuery.error}
                names={cubesQuery.data}
                emptyLabel="No cubes found on this server."
              />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="dimensions">
          <Card>
            <CardHeader>
              <CardTitle>Dimensions</CardTitle>
              <CardDescription>
                Read live from the TM1 server (control dimensions excluded).
              </CardDescription>
            </CardHeader>
            <CardContent>
              <NameList
                isPending={dimensionsQuery.isPending}
                isError={dimensionsQuery.isError}
                error={dimensionsQuery.error}
                names={dimensionsQuery.data}
                emptyLabel="No dimensions found on this server."
              />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="processes">
          <Card>
            <CardHeader>
              <CardTitle>Processes</CardTitle>
              <CardDescription>
                TI processes (control processes excluded).
              </CardDescription>
            </CardHeader>
            <CardContent>
              <NameList
                isPending={processesQuery.isPending}
                isError={processesQuery.isError}
                error={processesQuery.error}
                names={processesQuery.data}
                emptyLabel="No processes found on this server."
              />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="chores">
          <Card>
            <CardHeader>
              <CardTitle>Chores</CardTitle>
              <CardDescription>Scheduled process chains.</CardDescription>
            </CardHeader>
            <CardContent>
              <NameList
                isPending={choresQuery.isPending}
                isError={choresQuery.isError}
                error={choresQuery.error}
                names={choresQuery.data}
                emptyLabel="No chores found on this server."
              />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle>Recent Changes</CardTitle>
            <CardDescription>
              Draft and deployed changes to this connection.
            </CardDescription>
          </div>
          <Link
            href={`/deployments?connection=${connectionId}`}
            className={buttonVariants({ variant: "outline", size: "sm" })}
          >
            View All
            <ArrowRight className="ml-2 h-4 w-4" />
          </Link>
        </CardHeader>
        <CardContent>
          {changesQuery.isError ? (
            <p className="py-4 text-center text-sm text-destructive">
              Failed to load changes: {errorMessage(changesQuery.error)}
            </p>
          ) : changesQuery.isPending ? (
            <div className="space-y-2">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </div>
          ) : !changesQuery.data?.length ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              No changes yet.
            </p>
          ) : (
            <ul className="divide-y">
              {changesQuery.data.slice(0, 5).map((change) => (
                <li
                  key={change.id}
                  className="flex items-center justify-between py-2 text-sm"
                >
                  <span>
                    <span className="font-medium">{change.target_name}</span>
                    <span className="ml-2 text-xs text-muted-foreground">
                      {CHANGE_TYPE_LABEL[change.change_type]}
                    </span>
                  </span>
                  <Badge variant={STATUS_VARIANT[change.status]}>
                    {change.status.replace("_", " ")}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
