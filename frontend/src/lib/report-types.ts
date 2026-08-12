/**
 * Report automation types (DEVELOPER PREVIEW).
 *
 * Mirrors backend/src/schemas/reports.py. Kept in its own module rather
 * than added to lib/types.ts so the preview feature can be removed or
 * reshaped without touching the shipped types.
 */

export type ExecutionStatus =
  | "queued"
  | "assigned"
  | "running"
  | "succeeded"
  | "failed"
  | "timed_out"
  | "cancelled"
  | "retrying";

export type WorkerStatus =
  | "pending_enrollment"
  | "online"
  | "offline"
  | "busy"
  | "disabled"
  | "error";

export interface ReportWorkbook {
  id: string;
  name: string;
  filename: string;
  content_type: string;
  checksum: string;
  size_bytes: number;
  version: number;
  status: string;
  description: string | null;
  created_at: string;
}

export interface ReportDefinition {
  id: string;
  name: string;
  description: string | null;
  report_type: string;
  workbook_id: string | null;
  connection_id: string | null;
  worker_id: string | null;
  output_formats: string[];
  parameters: Record<string, unknown> | null;
  status: string;
  approval_status: string;
  created_at: string;
  updated_at: string;
}

export interface ReportWorker {
  id: string;
  name: string;
  description: string | null;
  status: WorkerStatus;
  version: string | null;
  os: string | null;
  excel_version: string | null;
  pafe_version: string | null;
  hostname: string | null;
  capabilities: string[];
  last_heartbeat_at: string | null;
  enrolled_at: string | null;
  disabled_at: string | null;
  last_error: string | null;
  created_at: string;
}

/** Returned exactly once, at registration. Never retrievable again. */
export interface WorkerEnrollment {
  worker: ReportWorker;
  enrollment_token: string;
  expires_at: string | null;
  instructions: string;
}

export interface ReportArtifact {
  id: string;
  report_execution_id: string;
  output_format: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  checksum: string;
  created_at: string;
}

export interface ReportExecution {
  id: string;
  report_id: string;
  workbook_id: string | null;
  worker_id: string | null;
  status: ExecutionStatus;
  trigger_type: string;
  correlation_id: string;
  attempt: number;
  max_attempts: number;
  parent_execution_id: string | null;
  queued_at: string;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  timeout_seconds: number;
  error_code: string | null;
  error_message: string | null;
  retry_class: string | null;
  diagnostics: Record<string, unknown> | null;
  created_at: string;
}

export interface ReportExecutionDetail extends ReportExecution {
  artifacts: ReportArtifact[];
  trace_log: string | null;
}

export interface RunNowResult {
  execution: ReportExecution;
  /** False when an identical request already produced this execution. */
  created: boolean;
}
