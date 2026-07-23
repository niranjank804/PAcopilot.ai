"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Boxes,
  Calendar,
  FileText,
  GitBranch,
  Layers,
  Lightbulb,
  Search,
  ShieldAlert,
  Target,
  Wrench,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { ObjectGraph } from "@/components/object-graph";
import { ApiError, apiRequest } from "@/lib/api-client";
import { CHANGE_TYPE_LABEL, STATUS_VARIANT } from "@/lib/change-format";
import { cn } from "@/lib/utils";
import type {
  ChoreDetail,
  CubeDetail,
  DimensionDetail,
  ModelObjectType,
  ObjectRelationships,
  ProcessDetail,
  TM1ChangeSummary,
  TM1Connection,
} from "@/lib/types";

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong.";
}

interface SelectedObject {
  type: ModelObjectType;
  name: string;
}

const TYPE_ICON: Record<ModelObjectType, typeof Boxes> = {
  cube: Boxes,
  dimension: Layers,
  process: GitBranch,
  chore: Calendar,
};

const TYPE_LABEL: Record<ModelObjectType, string> = {
  cube: "Cube",
  dimension: "Dimension",
  process: "Process",
  chore: "Chore",
};

const TYPE_LABEL_PLURAL: Record<ModelObjectType, string> = {
  cube: "Cubes",
  dimension: "Dimensions",
  process: "Processes",
  chore: "Chores",
};

const RECENT_KEY = (connectionId: string) => `pa-copilot-recent-${connectionId}`;
const RECENT_LIMIT = 6;

function readRecent(connectionId: string): SelectedObject[] {
  if (typeof window === "undefined") return [];

  try {
    const raw = window.localStorage.getItem(RECENT_KEY(connectionId));
    return raw ? (JSON.parse(raw) as SelectedObject[]) : [];
  } catch {
    return [];
  }
}

function pushRecent(connectionId: string, object: SelectedObject) {
  if (typeof window === "undefined") return;

  const existing = readRecent(connectionId).filter(
    (o) => !(o.type === object.type && o.name === object.name),
  );
  const next = [object, ...existing].slice(0, RECENT_LIMIT);
  window.localStorage.setItem(RECENT_KEY(connectionId), JSON.stringify(next));
}

function ObjectList({
  type,
  names,
  isPending,
  isError,
  search,
  selected,
  onSelect,
}: {
  type: ModelObjectType;
  names: string[] | undefined;
  isPending: boolean;
  isError: boolean;
  search: string;
  selected: SelectedObject | null;
  onSelect: (object: SelectedObject) => void;
}) {
  const Icon = TYPE_ICON[type];
  const filtered = (names ?? []).filter((name) =>
    name.toLowerCase().includes(search.toLowerCase()),
  );

  if (search && !filtered.length) return null;

  return (
    <div>
      <p className="mb-1 flex items-center gap-1.5 px-1 text-xs font-medium text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {TYPE_LABEL_PLURAL[type]} {names ? `(${filtered.length})` : ""}
      </p>
      {isError ? (
        <p className="px-1 text-xs text-destructive">Failed to load.</p>
      ) : isPending ? (
        <Skeleton className="h-16 w-full" />
      ) : (
        <div className="max-h-40 space-y-0.5 overflow-y-auto">
          {filtered.map((name) => (
            <button
              key={name}
              onClick={() => onSelect({ type, name })}
              className={cn(
                "w-full truncate rounded-md px-2 py-1 text-left text-sm hover:bg-accent",
                selected?.type === type && selected.name === name && "bg-accent font-medium",
              )}
              title={name}
            >
              {name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function MetadataPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [connectionId, setConnectionId] = useState<string | null>(
    () => searchParams.get("connection"),
  );
  const [selected, setSelected] = useState<SelectedObject | null>(null);
  const [search, setSearch] = useState("");
  // Bumped after every pushRecent() write so `recent` (read fresh from
  // localStorage on each render below, not cached in state) re-renders —
  // avoids a setState-in-effect just to mirror localStorage into state.
  const [, setRecentVersion] = useState(0);

  const connectionsQuery = useQuery({
    queryKey: ["tm1-connections"],
    queryFn: () => apiRequest<TM1Connection[]>("/tm1/connections"),
  });

  const activeConnectionId = connectionId ?? connectionsQuery.data?.[0]?.id ?? null;
  const recent = activeConnectionId ? readRecent(activeConnectionId) : [];

  const selectObject = (object: SelectedObject) => {
    setSelected(object);

    if (activeConnectionId) {
      pushRecent(activeConnectionId, object);
      setRecentVersion((v) => v + 1);
    }
  };

  const cubesQuery = useQuery({
    queryKey: ["tm1-cubes", activeConnectionId],
    queryFn: () => apiRequest<string[]>(`/tm1/connections/${activeConnectionId}/cubes`),
    enabled: activeConnectionId !== null,
  });

  const dimensionsQuery = useQuery({
    queryKey: ["tm1-dimensions", activeConnectionId],
    queryFn: () =>
      apiRequest<string[]>(`/tm1/connections/${activeConnectionId}/dimensions`),
    enabled: activeConnectionId !== null,
  });

  const processesQuery = useQuery({
    queryKey: ["tm1-processes", activeConnectionId],
    queryFn: () =>
      apiRequest<string[]>(`/tm1/connections/${activeConnectionId}/processes`),
    enabled: activeConnectionId !== null,
  });

  const choresQuery = useQuery({
    queryKey: ["tm1-chores", activeConnectionId],
    queryFn: () => apiRequest<string[]>(`/tm1/connections/${activeConnectionId}/chores`),
    enabled: activeConnectionId !== null,
  });

  const cubeDetailQuery = useQuery({
    queryKey: ["tm1-cube-detail", activeConnectionId, selected?.name],
    queryFn: () =>
      apiRequest<CubeDetail>(
        `/tm1/connections/${activeConnectionId}/cubes/${encodeURIComponent(selected!.name)}`,
      ),
    enabled: activeConnectionId !== null && selected?.type === "cube",
  });

  const cubeRulesQuery = useQuery({
    queryKey: ["tm1-cube-rules", activeConnectionId, selected?.name],
    queryFn: () =>
      apiRequest<{ name: string; rules: string | null }>(
        `/tm1/connections/${activeConnectionId}/cubes/${encodeURIComponent(selected!.name)}/rules`,
      ),
    enabled:
      activeConnectionId !== null &&
      selected?.type === "cube" &&
      !!cubeDetailQuery.data?.has_rules,
  });

  const dimensionDetailQuery = useQuery({
    queryKey: ["tm1-dimension-detail", activeConnectionId, selected?.name],
    queryFn: () =>
      apiRequest<DimensionDetail>(
        `/tm1/connections/${activeConnectionId}/dimensions/${encodeURIComponent(selected!.name)}`,
      ),
    enabled: activeConnectionId !== null && selected?.type === "dimension",
  });

  const processDetailQuery = useQuery({
    queryKey: ["tm1-process-detail", activeConnectionId, selected?.name],
    queryFn: () =>
      apiRequest<ProcessDetail>(
        `/tm1/connections/${activeConnectionId}/processes/${encodeURIComponent(selected!.name)}`,
      ),
    enabled: activeConnectionId !== null && selected?.type === "process",
  });

  const choreDetailQuery = useQuery({
    queryKey: ["tm1-chore-detail", activeConnectionId, selected?.name],
    queryFn: () =>
      apiRequest<ChoreDetail>(
        `/tm1/connections/${activeConnectionId}/chores/${encodeURIComponent(selected!.name)}`,
      ),
    enabled: activeConnectionId !== null && selected?.type === "chore",
  });

  const relationshipsQuery = useQuery({
    queryKey: ["tm1-relationships", activeConnectionId, selected?.type, selected?.name],
    queryFn: () =>
      apiRequest<ObjectRelationships>(
        `/tm1/connections/${activeConnectionId}/metadata/objects/${selected!.type}/${encodeURIComponent(selected!.name)}/relationships`,
      ),
    enabled: activeConnectionId !== null && selected !== null,
  });

  const changesQuery = useQuery({
    queryKey: ["tm1-changes", activeConnectionId],
    queryFn: () =>
      apiRequest<TM1ChangeSummary[]>(`/tm1/connections/${activeConnectionId}/changes`),
    enabled: activeConnectionId !== null,
  });

  const objectChanges = selected
    ? (changesQuery.data ?? []).filter((c) => c.target_name === selected.name)
    : [];

  const goToChat = (prompt: string, agent: string) => {
    router.push(`/chat?agent=${agent}&prompt=${encodeURIComponent(prompt)}`);
  };

  const [activeTab, setActiveTab] = useState("overview");

  const viewDeploymentsFor = (targetName: string) => {
    const change = (changesQuery.data ?? []).find((c) => c.target_name === targetName);
    router.push(
      change
        ? `/deployments?connection=${activeConnectionId}&change=${change.id}`
        : `/deployments?connection=${activeConnectionId}`,
    );
  };

  return (
    <div className="flex h-full gap-4">
      <aside className="flex w-72 shrink-0 flex-col gap-3 border-r pr-4">
        {activeConnectionId ? (
          <Select
            value={activeConnectionId}
            onValueChange={(value) => {
              setConnectionId(value);
              setSelected(null);
            }}
          >
            <SelectTrigger aria-label="Connection">
              <SelectValue placeholder="Select connection">
                {(value: string) =>
                  connectionsQuery.data?.find((c) => c.id === value)?.name ??
                  "Select connection"
                }
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {connectionsQuery.data?.map((connection) => (
                <SelectItem key={connection.id} value={connection.id}>
                  {connection.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <Skeleton className="h-9 w-full" />
        )}

        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search objects"
            className="pl-7"
          />
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto">
          {!search && recent.length ? (
            <div>
              <p className="mb-1 px-1 text-xs font-medium text-muted-foreground">
                Recently Viewed
              </p>
              <div className="space-y-0.5">
                {recent.map((object) => (
                  <button
                    key={`${object.type}-${object.name}`}
                    onClick={() => selectObject(object)}
                    className={cn(
                      "flex w-full items-center gap-1.5 truncate rounded-md px-2 py-1 text-left text-sm hover:bg-accent",
                      selected?.type === object.type &&
                        selected.name === object.name &&
                        "bg-accent font-medium",
                    )}
                  >
                    {object.name}
                    <span className="text-xs text-muted-foreground">
                      {TYPE_LABEL[object.type]}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          <ObjectList
            type="cube"
            names={cubesQuery.data}
            isPending={cubesQuery.isPending}
            isError={cubesQuery.isError}
            search={search}
            selected={selected}
            onSelect={selectObject}
          />
          <ObjectList
            type="dimension"
            names={dimensionsQuery.data}
            isPending={dimensionsQuery.isPending}
            isError={dimensionsQuery.isError}
            search={search}
            selected={selected}
            onSelect={selectObject}
          />
          <ObjectList
            type="process"
            names={processesQuery.data}
            isPending={processesQuery.isPending}
            isError={processesQuery.isError}
            search={search}
            selected={selected}
            onSelect={selectObject}
          />
          <ObjectList
            type="chore"
            names={choresQuery.data}
            isPending={choresQuery.isPending}
            isError={choresQuery.isError}
            search={search}
            selected={selected}
            onSelect={selectObject}
          />
        </div>
      </aside>

      <div className="flex-1 overflow-y-auto">
        {!selected ? (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-muted-foreground">
              Select an object on the left to explore it.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-2xl font-semibold tracking-tight">
                  {selected.name}
                </h1>
                <Badge variant="outline">{TYPE_LABEL[selected.type]}</Badge>
              </div>
            </div>

            <Tabs value={activeTab} onValueChange={setActiveTab}>
              <TabsList>
                <TabsTrigger value="overview">Overview</TabsTrigger>
                <TabsTrigger value="relationships">Relationships</TabsTrigger>
                <TabsTrigger value="graph">Graph</TabsTrigger>
                <TabsTrigger value="changes">
                  Recent Changes {objectChanges.length ? `(${objectChanges.length})` : ""}
                </TabsTrigger>
                <TabsTrigger value="ai">AI Analysis</TabsTrigger>
              </TabsList>

              <TabsContent value="overview">
                <Card>
                  <CardContent className="space-y-4 py-4">
                    {selected.type === "cube" ? (
                      cubeDetailQuery.isError ? (
                        <p className="text-sm text-destructive">
                          Failed to load: {errorMessage(cubeDetailQuery.error)}
                        </p>
                      ) : cubeDetailQuery.isPending ? (
                        <Skeleton className="h-24 w-full" />
                      ) : (
                        <>
                          <div className="flex items-center gap-2">
                            {cubeDetailQuery.data?.has_rules ? (
                              <Badge variant="secondary">has rules</Badge>
                            ) : (
                              <Badge variant="outline">no rules</Badge>
                            )}
                          </div>
                          <div>
                            <p className="mb-1 text-xs font-medium text-muted-foreground">
                              Dimensions
                            </p>
                            <div className="flex flex-wrap gap-1">
                              {cubeDetailQuery.data?.dimensions.map((dim) => (
                                <button
                                  key={dim}
                                  onClick={() => selectObject({ type: "dimension", name: dim })}
                                >
                                  <Badge variant="outline" className="cursor-pointer hover:bg-accent">
                                    {dim}
                                  </Badge>
                                </button>
                              ))}
                            </div>
                          </div>
                          {cubeDetailQuery.data?.has_rules ? (
                            <div>
                              <p className="mb-1 text-xs font-medium text-muted-foreground">
                                Rules
                              </p>
                              {cubeRulesQuery.isPending ? (
                                <Skeleton className="h-24 w-full" />
                              ) : (
                                <pre className="max-h-72 overflow-auto rounded-md bg-muted p-3 text-xs whitespace-pre-wrap">
                                  {cubeRulesQuery.data?.rules || "(empty)"}
                                </pre>
                              )}
                            </div>
                          ) : null}
                        </>
                      )
                    ) : null}

                    {selected.type === "dimension" ? (
                      dimensionDetailQuery.isError ? (
                        <p className="text-sm text-destructive">
                          Failed to load: {errorMessage(dimensionDetailQuery.error)}
                        </p>
                      ) : dimensionDetailQuery.isPending ? (
                        <Skeleton className="h-16 w-full" />
                      ) : (
                        <div>
                          <p className="mb-1 text-xs font-medium text-muted-foreground">
                            Hierarchies
                          </p>
                          <div className="flex flex-wrap gap-1">
                            {dimensionDetailQuery.data?.hierarchy_names.map((h) => (
                              <Badge key={h} variant="outline">
                                {h}
                              </Badge>
                            ))}
                          </div>
                        </div>
                      )
                    ) : null}

                    {selected.type === "process" ? (
                      processDetailQuery.isError ? (
                        <p className="text-sm text-destructive">
                          Failed to load: {errorMessage(processDetailQuery.error)}
                        </p>
                      ) : processDetailQuery.isPending ? (
                        <Skeleton className="h-40 w-full" />
                      ) : (
                        <>
                          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                            <span>
                              Datasource: {processDetailQuery.data?.datasource_type}
                              {processDetailQuery.data?.datasource_name
                                ? ` · ${processDetailQuery.data.datasource_name}`
                                : ""}
                            </span>
                            {processDetailQuery.data?.has_security_access ? (
                              <Badge variant="secondary">security access</Badge>
                            ) : null}
                          </div>
                          {processDetailQuery.data?.parameter_names.length ? (
                            <div>
                              <p className="mb-1 text-xs font-medium text-muted-foreground">
                                Parameters
                              </p>
                              <div className="flex flex-wrap gap-1">
                                {processDetailQuery.data.parameter_names.map((p) => (
                                  <Badge key={p} variant="outline">
                                    {p}
                                  </Badge>
                                ))}
                              </div>
                            </div>
                          ) : null}
                          {(["prolog", "metadata", "data", "epilog"] as const).map((section) =>
                            processDetailQuery.data?.[section] ? (
                              <div key={section}>
                                <p className="mb-1 text-xs font-medium text-muted-foreground capitalize">
                                  {section}
                                </p>
                                <pre className="max-h-56 overflow-auto rounded-md bg-muted p-3 text-xs whitespace-pre-wrap">
                                  {processDetailQuery.data[section]}
                                </pre>
                              </div>
                            ) : null,
                          )}
                        </>
                      )
                    ) : null}

                    {selected.type === "chore" ? (
                      choreDetailQuery.isError ? (
                        <p className="text-sm text-destructive">
                          Failed to load: {errorMessage(choreDetailQuery.error)}
                        </p>
                      ) : choreDetailQuery.isPending ? (
                        <Skeleton className="h-16 w-full" />
                      ) : (
                        <>
                          <Badge variant={choreDetailQuery.data?.active ? "default" : "secondary"}>
                            {choreDetailQuery.data?.active ? "active" : "inactive"}
                          </Badge>
                          <div>
                            <p className="mb-1 text-xs font-medium text-muted-foreground">
                              Process chain
                            </p>
                            <div className="flex flex-wrap items-center gap-1 text-sm">
                              {choreDetailQuery.data?.process_names.map((p, i) => (
                                <span key={p} className="flex items-center gap-1">
                                  {i > 0 ? <span className="text-muted-foreground">→</span> : null}
                                  <button
                                    onClick={() => selectObject({ type: "process", name: p })}
                                    className="hover:underline"
                                  >
                                    {p}
                                  </button>
                                </span>
                              ))}
                            </div>
                          </div>
                        </>
                      )
                    ) : null}
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="relationships">
                <div className="grid gap-4 sm:grid-cols-2">
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">Depends on</CardTitle>
                      <CardDescription>Objects this one references.</CardDescription>
                    </CardHeader>
                    <CardContent>
                      {relationshipsQuery.isError ? (
                        <p className="text-sm text-destructive">
                          Failed to load: {errorMessage(relationshipsQuery.error)}
                        </p>
                      ) : relationshipsQuery.isPending ? (
                        <Skeleton className="h-24 w-full" />
                      ) : !relationshipsQuery.data?.outgoing.length ? (
                        <p className="text-sm text-muted-foreground">None found.</p>
                      ) : (
                        <ul className="space-y-1">
                          {relationshipsQuery.data.outgoing.map((rel, index) => (
                            <li key={index} className="flex items-center gap-2 text-sm">
                              <Badge variant="outline" className="text-xs">
                                {rel.object_type}
                              </Badge>
                              {["cube", "dimension", "process", "chore"].includes(rel.object_type) ? (
                                <button
                                  onClick={() =>
                                    selectObject({
                                      type: rel.object_type as ModelObjectType,
                                      name: rel.name,
                                    })
                                  }
                                  className="hover:underline"
                                >
                                  {rel.name}
                                </button>
                              ) : (
                                <span>{rel.name}</span>
                              )}
                              <span className="text-xs text-muted-foreground">
                                ({rel.relationship_type})
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </CardContent>
                  </Card>

                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">Depended on by</CardTitle>
                      <CardDescription>Objects that reference this one.</CardDescription>
                    </CardHeader>
                    <CardContent>
                      {relationshipsQuery.isError ? (
                        <p className="text-sm text-destructive">
                          Failed to load: {errorMessage(relationshipsQuery.error)}
                        </p>
                      ) : relationshipsQuery.isPending ? (
                        <Skeleton className="h-24 w-full" />
                      ) : !relationshipsQuery.data?.incoming.length ? (
                        <p className="text-sm text-muted-foreground">None found.</p>
                      ) : (
                        <ul className="space-y-1">
                          {relationshipsQuery.data.incoming.map((rel, index) => (
                            <li key={index} className="flex items-center gap-2 text-sm">
                              <Badge variant="outline" className="text-xs">
                                {rel.object_type}
                              </Badge>
                              {["cube", "dimension", "process", "chore"].includes(rel.object_type) ? (
                                <button
                                  onClick={() =>
                                    selectObject({
                                      type: rel.object_type as ModelObjectType,
                                      name: rel.name,
                                    })
                                  }
                                  className="hover:underline"
                                >
                                  {rel.name}
                                </button>
                              ) : (
                                <span>{rel.name}</span>
                              )}
                              <span className="text-xs text-muted-foreground">
                                ({rel.relationship_type})
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </CardContent>
                  </Card>
                </div>
              </TabsContent>

              <TabsContent value="graph">
                {activeConnectionId ? (
                  <ObjectGraph
                    connectionId={activeConnectionId}
                    focus={selected}
                    changes={changesQuery.data ?? []}
                    onOpenWorkspace={(object) => {
                      selectObject(object);
                      setActiveTab("overview");
                    }}
                    onDiscussWithAI={goToChat}
                    onViewDeployments={viewDeploymentsFor}
                  />
                ) : null}
              </TabsContent>

              <TabsContent value="changes">
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">Recent Changes</CardTitle>
                    <CardDescription>
                      Drafts and deployments targeting &quot;{selected.name}&quot;.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {changesQuery.isError ? (
                      <p className="text-sm text-destructive">
                        Failed to load: {errorMessage(changesQuery.error)}
                      </p>
                    ) : changesQuery.isPending ? (
                      <Skeleton className="h-16 w-full" />
                    ) : !objectChanges.length ? (
                      <p className="text-sm text-muted-foreground">
                        No changes for this object yet.
                      </p>
                    ) : (
                      <ul className="divide-y">
                        {objectChanges.map((change) => (
                          <li key={change.id}>
                            <button
                              onClick={() =>
                                router.push(
                                  `/deployments?connection=${activeConnectionId}&change=${change.id}`,
                                )
                              }
                              className="flex w-full items-center justify-between py-2 text-left text-sm hover:underline"
                            >
                              <span>
                                {CHANGE_TYPE_LABEL[change.change_type]} ·{" "}
                                {new Date(change.created_at).toLocaleString()}
                              </span>
                              <Badge variant={STATUS_VARIANT[change.status]}>
                                {change.status.replace("_", " ")}
                              </Badge>
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="ai">
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">Ask the AI</CardTitle>
                    <CardDescription>
                      Opens the AI Workspace with this object already in context.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="grid gap-2 sm:grid-cols-2">
                    <Button
                      variant="outline"
                      className="justify-start"
                      onClick={() =>
                        goToChat(
                          `Explain what the ${selected.type} "${selected.name}" does and how it fits into the TM1 model in connection ${activeConnectionId}.`,
                          "developer",
                        )
                      }
                    >
                      <Lightbulb className="mr-2 h-4 w-4" />
                      Explain this {TYPE_LABEL[selected.type].toLowerCase()}
                    </Button>
                    <Button
                      variant="outline"
                      className="justify-start"
                      onClick={() =>
                        goToChat(
                          `Analyze the downstream impact of changing the ${selected.type} "${selected.name}" in connection ${activeConnectionId}. Use the dependency graph and summarize the risk.`,
                          "architect",
                        )
                      }
                    >
                      <Target className="mr-2 h-4 w-4" />
                      Analyze impact
                    </Button>
                    <Button
                      variant="outline"
                      className="justify-start"
                      onClick={() =>
                        goToChat(
                          `I'd like to discuss the ${selected.type} "${selected.name}" in connection ${activeConnectionId}. Look up its current state and dependencies first.`,
                          "architect",
                        )
                      }
                    >
                      <ShieldAlert className="mr-2 h-4 w-4" />
                      Discuss with Architect
                    </Button>
                    <Button
                      variant="outline"
                      className="justify-start"
                      onClick={() =>
                        goToChat(
                          `I'd like to discuss the ${selected.type} "${selected.name}" in connection ${activeConnectionId}. Look up its current state and dependencies first.`,
                          "developer",
                        )
                      }
                    >
                      <Wrench className="mr-2 h-4 w-4" />
                      Discuss with Developer
                    </Button>
                    <Button
                      variant="outline"
                      className="justify-start sm:col-span-2"
                      onClick={() =>
                        goToChat(
                          `Write clear documentation for the ${selected.type} "${selected.name}" in connection ${activeConnectionId}: its purpose, its structure, and its key dependencies. Look up its current state first.`,
                          "documentation",
                        )
                      }
                    >
                      <FileText className="mr-2 h-4 w-4" />
                      Generate documentation
                    </Button>
                  </CardContent>
                </Card>
              </TabsContent>
            </Tabs>
          </div>
        )}
      </div>
    </div>
  );
}
