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
