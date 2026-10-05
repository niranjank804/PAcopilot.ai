export type MonitorKind =
  | "process_failure"
  | "performance_regression"
  | "dimension_growth"
  | "security_change"
  | "model_change"
  | "deployment";

export type Severity = "info" | "warning" | "critical";

export interface MonitorRule {
  id: string;
  connection_id: string;
  name: string;
  kind: MonitorKind;
  params: Record<string, string | number | null>;
  status: "active" | "paused" | "proposed";
  source: "human" | "ai";
  rationale: string | null;
  interval_minutes: number;
  notify: string[];
  last_checked_at: string | null;
  last_error: string | null;
  consecutive_errors: number;
  created_by: string;
  created_at: string;
}

export interface MonitorAlert {
  id: string;
  rule_id: string;
  connection_id: string;
  severity: Severity;
  title: string;
  detail: string | null;
  evidence: Record<string, unknown> | null;
  fired_at: string;
  status: "open" | "acknowledged" | "resolved";
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  emailed: boolean;
}

export interface MonitoringSetup {
  kinds: { kind: MonitorKind; label: string }[];
  email_configured: boolean;
  schedule_path: string;
}

export const OPEN_ALERTS_KEY = ["monitoring", "open-count"] as const;

/** The parameters each kind asks for, in the form. */
export const KIND_FIELDS: Record<
  MonitorKind,
  { key: string; label: string; type: "text" | "number"; required?: boolean; placeholder?: string; initial?: string }[]
> = {
  process_failure: [
    { key: "process_name", label: "Process (blank = any process)", type: "text", placeholder: "Load Sales" },
  ],
  performance_regression: [
    { key: "process_name", label: "Process", type: "text", required: true, placeholder: "Workforce Planning" },
    { key: "factor", label: "Alert at this many times the average", type: "number", initial: "2" },
    { key: "window_days", label: "Average over (days)", type: "number", initial: "30" },
  ],
  dimension_growth: [
    { key: "dimension_name", label: "Dimension", type: "text", required: true, placeholder: "Employee" },
    { key: "max_growth_percent", label: "Alert above this growth (%)", type: "number", initial: "10" },
  ],
  security_change: [],
  model_change: [],
  deployment: [],
};
