import type { Environment } from "@/lib/types";

export type WorkItemStatus = "open" | "in_progress" | "resolved" | "closed";

export const STATUS_LABEL: Record<WorkItemStatus, string> = {
  open: "Open",
  in_progress: "In progress",
  resolved: "Resolved",
  closed: "Closed",
};

export interface WorkItem {
  id: string;
  reference: string;
  title: string;
  description: string | null;
  status: WorkItemStatus;
  root_cause: string | null;
  resolution: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  kind?: "work" | "incident";
  severity?: IncidentSeverity | null;
  connection_id?: string | null;
  cube_name?: string | null;
  process_name?: string | null;
}

export type IncidentSeverity = "low" | "medium" | "high" | "critical";

export interface Suspect {
  score: number;
  kind: string;
  title: string;
  detail: string | null;
  at: string | null;
  mitigation: {
    action: "rollback" | "diagnose" | "review";
    label: string;
    change_id?: string;
    process?: string;
    alert_id?: string;
  };
}

export interface Investigation {
  id: string;
  created_at: string;
  window_hours: number;
  summary: string;
  findings: {
    summary: string;
    environment: Environment;
    connection: string;
    window_hours: number;
    affected: {
      cubes: string[];
      rule_sources: string[];
      writers: Record<string, string[]>;
      reported_process: string | null;
    };
    suspects: Suspect[];
    evidence: { changes: unknown[]; runs: unknown[]; model_extractions: number; open_alerts: number };
    notes: string[];
    applied_nothing: string;
  };
}

export interface TimelineEvent {
  at: string;
  kind: string;
  title: string;
  detail: string | null;
  actor: string | null;
  link_id: string | null;
}

export interface LinkedRecord {
  link_id: string;
  kind: "conversation" | "change";
  target_id: string;
  available: boolean;
  title: string;
  note: string | null;
  linked_at: string;
  linked_by_name: string | null;
  owner_name: string | null;
  messages: number | null;
  status: string | null;
  connection_id: string | null;
  connection_name: string | null;
  environment: Environment | null;
}

export interface WorkItemDetail {
  item: WorkItem;
  created_by_name: string | null;
  progress: { key: string; label: string; done: boolean }[];
  links: LinkedRecord[];
  events: TimelineEvent[];
  /** Incidents, newest first; null when you may not use the server. */
  investigations?: Investigation[] | null;
}

export interface SharedConversation {
  id: string;
  title: string | null;
  owner_id: string;
  owner_name: string;
  created_at: string;
  updated_at: string;
}

export interface ActivityChange {
  id: string;
  connection_id: string;
  connection_name: string;
  environment: Environment;
  change_type: string;
  target_name: string;
  status: string;
  awaiting_approval: boolean;
  created_at: string;
  executed_at: string | null;
  created_by_name: string | null;
}

export interface TeamActivity {
  open_work_items: WorkItem[];
  shared_conversations: SharedConversation[];
  changes: ActivityChange[];
  health: {
    connection_id: string;
    connection_name: string;
    environment: Environment;
    score: number;
    grade: string;
    scanned_at: string;
  }[];
}

export function changeHref(connectionId: string, changeId: string): string {
  return `/deployments?connection=${connectionId}&change=${changeId}`;
}

export function when(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** What "Work this PBI" asks the TI agent to do, in order. Every step that
 * changes TM1 stays a draft for a person to approve. */
export function workThisPbiPrompt(reference: string): string {
  return [
    `Work ${reference} with me, step by step.`,
    "1) Read it with get_work_item. List what it does not say (objects, coordinates, periods, versions, signs, " +
      "scope, edge cases) with a recommended default for each, and save a clarification email draft on the work " +
      "item (save_work_item_document, kind clarification_email). It is a draft; nothing is sent.",
    "2) Search the Knowledge Base and Engineering Memory for our TI house template and reference processes, and " +
      "say which you will follow. If there is none, say so and use the closest existing processes on the server " +
      "as the pattern.",
    "3) Read the current state of every object the change touches and save it as evidence.",
    "4) Draft the code to that pattern, compile it on the server without saving, then propose it as a change and " +
      "link the change to the work item.",
    "5) Save a test plan. Propose any test data as cell writes on empty leaf cells only, and a test run, for me " +
      "to approve.",
    `6) After I deploy and run it, read the results back from the cube, save the test results and evidence, ` +
      `propose public views named '${reference} - 1 ...', '${reference} - 2 ...' for the result, source and ` +
      "drivers, and save the delivery document and completion email.",
    "Stop and ask me whenever a decision is mine, and never say something was run or verified unless you read " +
      "it back.",
  ].join("\n");
}
