"use client";

import "@xyflow/react/dist/style.css";

import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import {
  Boxes,
  Calendar,
  FileText,
  GitBranch,
  Layers,
  Loader2,
  Locate,
  MessageSquare,
  Rocket,
  Search,
  Target,
  X,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, apiRequest } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type {
  ModelObjectType,
  ObjectRelationships,
  TM1ChangeSummary,
} from "@/lib/types";

const TIER_SPACING_Y = 110;
const NODE_SPACING_X = 200;
const MAX_NODES = 80;

const TYPE_STYLE: Record<
  string,
  { icon: typeof Boxes; color: string }
> = {
  cube: { icon: Boxes, color: "border-blue-500 bg-blue-500/10 text-blue-700 dark:text-blue-300" },
  dimension: { icon: Layers, color: "border-purple-500 bg-purple-500/10 text-purple-700 dark:text-purple-300" },
  process: { icon: GitBranch, color: "border-amber-500 bg-amber-500/10 text-amber-700 dark:text-amber-300" },
  chore: { icon: Calendar, color: "border-emerald-500 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" },
};

interface GraphNodeData extends Record<string, unknown> {
  objectType: string;
  name: string;
  isCenter: boolean;
  hasChange: boolean;
}

function ObjectNode({ data, selected }: NodeProps<Node<GraphNodeData>>) {
  const style = TYPE_STYLE[data.objectType] ?? TYPE_STYLE.cube;
  const Icon = style.icon;

  return (
    <div
      className={cn(
        "flex items-center gap-1.5 rounded-lg border-2 bg-background px-3 py-1.5 text-xs shadow-sm",
        style.color,
        data.isCenter && "ring-2 ring-primary ring-offset-2 ring-offset-background",
        selected && "outline outline-2 outline-foreground",
      )}
    >
      <Handle type="target" position={Position.Top} className="!opacity-0" />
      <Icon className="h-3.5 w-3.5 shrink-0" />
      <span className="max-w-36 truncate font-medium">{data.name}</span>
      {data.hasChange ? (
        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-destructive" title="Has changes" />
      ) : null}
      <Handle type="source" position={Position.Bottom} className="!opacity-0" />
    </div>
  );
}

const nodeTypes = { object: ObjectNode };

function nodeId(type: string, name: string) {
  return `${type}:${name}`;
}

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong.";
}

interface ObjectGraphProps {
  connectionId: string;
  focus: { type: ModelObjectType; name: string };
  changes: TM1ChangeSummary[];
  onOpenWorkspace: (object: { type: ModelObjectType; name: string }) => void;
  onDiscussWithAI: (prompt: string, agent: string) => void;
  onViewDeployments: (targetName: string) => void;
}

function GraphInner({
  connectionId,
  focus,
  changes,
  onOpenWorkspace,
  onDiscussWithAI,
  onViewDeployments,
}: ObjectGraphProps) {
  const { fitView, setCenter, getNode } = useReactFlow<Node<GraphNodeData>>();
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<GraphNodeData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<Set<string>>(
    new Set(["cube", "dimension", "process", "chore"]),
  );
  const [search, setSearch] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);

  const focusId = nodeId(focus.type, focus.name);
  const changedNames = useMemo(
    () => new Set(changes.map((c) => c.target_name)),
    [changes],
  );

  const recenterTier = useCallback((currentNodes: Node<GraphNodeData>[], tier: number) => {
    const inTier = currentNodes.filter((n) => n.position.y === tier * TIER_SPACING_Y);
    const start = -((inTier.length - 1) * NODE_SPACING_X) / 2;

    inTier.forEach((n, index) => {
      n.position.x = start + index * NODE_SPACING_X;
    });
  }, []);

  const resetGraph = useCallback(() => {
    const centerNode: Node<GraphNodeData> = {
      id: focusId,
      type: "object",
      position: { x: 0, y: 0 },
      data: {
        objectType: focus.type,
        name: focus.name,
        isCenter: true,
        hasChange: changedNames.has(focus.name),
      },
    };
    setNodes([centerNode]);
    setEdges([]);
    setExpanded(new Set());
    setSelectedId(focusId);
    setLoadError(null);
  }, [focusId, focus.type, focus.name, changedNames, setNodes, setEdges]);

  const expandNode = useCallback(
    async (type: string, name: string) => {
      const id = nodeId(type, name);

      if (expanded.has(id)) return;
      if (nodes.length >= MAX_NODES) {
        setLoadError(`Graph is capped at ${MAX_NODES} nodes — reset to explore a different area.`);
        return;
      }

      setLoadingId(id);
      setLoadError(null);

      try {
        const rel = await apiRequest<ObjectRelationships>(
          `/tm1/connections/${connectionId}/metadata/objects/${type}/${encodeURIComponent(name)}/relationships`,
        );

        setExpanded((prev) => new Set(prev).add(id));

        setNodes((currentNodes) => {
          const parent = currentNodes.find((n) => n.id === id);
          const parentTier = parent ? parent.position.y / TIER_SPACING_Y : 0;
          const existingIds = new Set(currentNodes.map((n) => n.id));
          const additions: Node<GraphNodeData>[] = [];

          for (const dep of rel.outgoing) {
            const depId = nodeId(dep.object_type, dep.name);
            if (!existingIds.has(depId) && additions.every((a) => a.id !== depId)) {
              additions.push({
                id: depId,
                type: "object",
                position: { x: 0, y: (parentTier - 1) * TIER_SPACING_Y },
                data: {
                  objectType: dep.object_type,
                  name: dep.name,
                  isCenter: false,
                  hasChange: changedNames.has(dep.name),
                },
              });
            }
          }

          for (const dep of rel.incoming) {
            const depId = nodeId(dep.object_type, dep.name);
            if (!existingIds.has(depId) && additions.every((a) => a.id !== depId)) {
              additions.push({
                id: depId,
                type: "object",
                position: { x: 0, y: (parentTier + 1) * TIER_SPACING_Y },
                data: {
                  objectType: dep.object_type,
                  name: dep.name,
                  isCenter: false,
                  hasChange: changedNames.has(dep.name),
                },
              });
            }
          }

          const next = [...currentNodes, ...additions];
          const touchedTiers = new Set(additions.map((a) => a.position.y / TIER_SPACING_Y));
          touchedTiers.forEach((tier) => recenterTier(next, tier));

          return next;
        });

        setEdges((currentEdges) => {
          const existingKeys = new Set(currentEdges.map((e) => e.id));
          const additions: Edge[] = [];

          for (const dep of [...rel.outgoing]) {
            const depId = nodeId(dep.object_type, dep.name);
            const edgeId = `${id}->${depId}:${dep.relationship_type}`;
            if (!existingKeys.has(edgeId)) {
              additions.push({
                id: edgeId,
                source: id,
                target: depId,
                label: dep.relationship_type,
                style: { strokeWidth: 1.5 },
              });
            }
          }

          for (const dep of rel.incoming) {
            const depId = nodeId(dep.object_type, dep.name);
            const edgeId = `${depId}->${id}:${dep.relationship_type}`;
            if (!existingKeys.has(edgeId)) {
              additions.push({
                id: edgeId,
                source: depId,
                target: id,
                label: dep.relationship_type,
                style: { strokeWidth: 1.5 },
              });
            }
          }

          return [...currentEdges, ...additions];
        });
      } catch (error) {
        setLoadError(errorMessage(error));
      } finally {
        setLoadingId(null);
      }
    },
    [connectionId, expanded, nodes.length, changedNames, setNodes, setEdges, recenterTier],
  );

  // Rebuild the graph whenever the explorer's selected object changes, and
  // auto-expand it once so there's always something to look at immediately.
  const [lastFocusId, setLastFocusId] = useState<string | null>(null);
  if (lastFocusId !== focusId) {
    setLastFocusId(focusId);
    resetGraph();
  }

  const visibleNodes = useMemo(
    () =>
      nodes.filter(
        (n) =>
          typeFilter.has(n.data.objectType) &&
          (!search || n.data.name.toLowerCase().includes(search.toLowerCase())),
      ),
    [nodes, typeFilter, search],
  );
  const visibleIds = useMemo(() => new Set(visibleNodes.map((n) => n.id)), [visibleNodes]);
  const visibleEdges = useMemo(
    () => edges.filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target)),
    [edges, visibleIds],
  );

  const selectedNode = selectedId ? getNode(selectedId) : undefined;

  const toggleType = (type: string) => {
    setTypeFilter((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  };

  const runSearch = () => {
    const match = visibleNodes.find((n) =>
      n.data.name.toLowerCase().includes(search.toLowerCase()),
    );
    if (match) {
      setCenter(match.position.x, match.position.y, { zoom: 1.2, duration: 400 });
      setSelectedId(match.id);
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runSearch()}
            placeholder="Search in graph"
            className="h-8 w-48 pl-7 text-sm"
          />
        </div>
        {(["cube", "dimension", "process", "chore"] as const).map((type) => {
          const style = TYPE_STYLE[type];
          const Icon = style.icon;
          return (
            <button key={type} onClick={() => toggleType(type)}>
              <Badge
                variant={typeFilter.has(type) ? "secondary" : "outline"}
                className={cn("gap-1", !typeFilter.has(type) && "opacity-40")}
              >
                <Icon className="h-3 w-3" />
                {type}
              </Badge>
            </button>
          );
        })}
        <Button variant="outline" size="sm" onClick={() => fitView({ duration: 300 })}>
          <Locate className="mr-1.5 h-3.5 w-3.5" />
          Fit view
        </Button>
        <Button variant="outline" size="sm" onClick={resetGraph}>
          Reset
        </Button>
        <span className="text-xs text-muted-foreground">
          {nodes.length} node{nodes.length === 1 ? "" : "s"}
        </span>
        {loadError ? <span className="text-xs text-destructive">{loadError}</span> : null}
      </div>

      <div className="relative h-[520px] rounded-md border">
        <ReactFlow
          nodes={visibleNodes}
          edges={visibleEdges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={(_, node) => setSelectedId(node.id)}
          onNodeDoubleClick={(_, node) =>
            expandNode(node.data.objectType, node.data.name)
          }
          onPaneClick={() => setSelectedId(null)}
          fitView
          minZoom={0.2}
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>

        {selectedNode ? (
          <div className="absolute right-3 top-3 w-56 rounded-md border bg-card p-3 shadow-md">
            <div className="mb-2 flex items-start justify-between gap-2">
              <div>
                <p className="text-sm font-medium">{selectedNode.data.name}</p>
                <p className="text-xs capitalize text-muted-foreground">
                  {selectedNode.data.objectType}
                </p>
              </div>
              <button onClick={() => setSelectedId(null)} aria-label="Close panel">
                <X className="h-3.5 w-3.5 text-muted-foreground hover:text-foreground" />
              </button>
            </div>
            <div className="space-y-1.5">
              <Button
                size="sm"
                variant="outline"
                className="w-full justify-start text-xs"
                disabled={loadingId === selectedNode.id || expanded.has(selectedNode.id)}
                onClick={() =>
                  expandNode(selectedNode.data.objectType, selectedNode.data.name)
                }
              >
                {loadingId === selectedNode.id ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Target className="mr-1.5 h-3.5 w-3.5" />
                )}
                {expanded.has(selectedNode.id) ? "Expanded" : "Expand neighbors"}
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="w-full justify-start text-xs"
                onClick={() =>
                  onOpenWorkspace({
                    type: selectedNode.data.objectType as ModelObjectType,
                    name: selectedNode.data.name,
                  })
                }
              >
                <FileText className="mr-1.5 h-3.5 w-3.5" />
                Open Workspace
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="w-full justify-start text-xs"
                onClick={() =>
                  onDiscussWithAI(
                    `I'd like to discuss the ${selectedNode.data.objectType} "${selectedNode.data.name}" in connection ${connectionId}. Look up its current state and dependencies first.`,
                    "architect",
                  )
                }
              >
                <MessageSquare className="mr-1.5 h-3.5 w-3.5" />
                Discuss with AI
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="w-full justify-start text-xs"
                onClick={() => onViewDeployments(selectedNode.data.name)}
              >
                <Rocket className="mr-1.5 h-3.5 w-3.5" />
                View Deployments
                {selectedNode.data.hasChange ? (
                  <span className="ml-auto h-1.5 w-1.5 rounded-full bg-destructive" />
                ) : null}
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function ObjectGraph(props: ObjectGraphProps) {
  return (
    <ReactFlowProvider>
      <GraphInner {...props} />
    </ReactFlowProvider>
  );
}
