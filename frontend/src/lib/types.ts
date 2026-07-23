// Mirrors the shapes returned by the backend's ApiResponse[T] envelope for
// the endpoints the dashboard consumes. Kept minimal/hand-written for now —
// generate from the OpenAPI schema once there are enough consumers to
// justify the tooling.

export interface TM1Connection {
  id: string;
  name: string;
  address: string;
  port: number;
  ssl: boolean;
  username: string;
  is_active: boolean;
  authentication_type: "native" | "v12_saas";
  tenant: string | null;
  database: string | null;
}

export type RegistrationStatus = "pending" | "approved" | "rejected";

export interface AppUser {
  id: string;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  is_active: boolean;
  organization_id: string;
  registration_status: RegistrationStatus;
}

export interface RoleInfo {
  id: string;
  organization_id: string | null;
  name: string;
  description: string | null;
  is_system: boolean;
}

export type ChangeType =
  | "update_rules"
  | "create_process"
  | "update_process"
  | "delete_process";

export type ChangeStatus =
  | "draft"
  | "executed"
  | "failed"
  | "rolled_back"
  | "rejected";

export interface RelatedObject {
  object_type: string;
  name: string;
  relationship_type: string;
}

// Raw shape of TM1's /CompileProcess REST response — surfaced verbatim by
// process_service.compile_process_dryrun/compile_process_on_server.
export interface ProcessSyntaxError {
  Message: string;
  Procedure: string;
  LineNumber: number;
}

export type ModelObjectType = "cube" | "dimension" | "process" | "chore";

export interface CubeDetail {
  name: string;
  dimensions: string[];
  has_rules: boolean;
}

export interface DimensionDetail {
  name: string;
  hierarchy_names: string[];
}

export interface ProcessDetail {
  name: string;
  datasource_type: string;
  datasource_name: string;
  datasource_view: string;
  has_security_access: boolean;
  parameter_names: string[];
  prolog: string;
  metadata: string;
  data: string;
  epilog: string;
}

export interface ChoreDetail {
  name: string;
  active: boolean;
  process_names: string[];
}

export interface ObjectRelationships {
  object_type: string;
  name: string;
  outgoing: RelatedObject[];
  incoming: RelatedObject[];
}

export interface KnowledgeDocument {
  id: string;
  filename: string;
  content_type: string;
  processing_status: string;
  error_message: string | null;
  created_at: string;
}

export interface Citation {
  document_id: string;
  filename: string;
  chunk_index: number;
  score: number;
}

export interface AskResponseBody {
  conversation_id: string;
  message_id: string;
  content: string;
  model: string;
  usage: ChatUsage;
  citations: Citation[];
}

export interface ExplainErrorResponseBody {
  error_type: string;
  severity: string;
  conversation_id: string;
  message_id: string;
  content: string;
  model: string;
  usage: ChatUsage;
  citations: Citation[];
}

export interface VisualizeCell {
  label: string;
  value: number;
}

export interface VisualizeResponseBody {
  cube_name: string;
  mdx: string;
  summary: string;
  cells: VisualizeCell[];
}


export interface ModelUsage {
  model: string;
  requests: number;
  total_tokens: number;
  total_cost_usd: number;
}

export interface UsageSummary {
  total_requests: number;
  total_tokens: number;
  total_cost_usd: number;
  by_model: ModelUsage[];
}

export interface ToolUsage {
  tool_name: string;
  total_calls: number;
  success_count: number;
  error_count: number;
  avg_duration_ms: number;
}

export interface TM1ConnectionStatus {
  connection_id: string;
  name: string;
  state: "closed" | "half_open" | "open";
  failure_count: number;
}

export interface ChatAttachmentInput {
  filename: string;
  content_type: string;
  data: string; // base64, no data: URL prefix
}

export interface AgentInfo {
  name: string;
  description: string;
  max_tool_rounds: number;
  tool_names: string[] | null;
  safety_notes: string[] | null;
}

export interface ChatUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
}

export interface ChatResponseBody {
  conversation_id: string;
  message_id: string;
  content: string;
  model: string;
  usage: ChatUsage;
}

export interface ConversationSummary {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface MessageResponse {
  id: string;
  role: string;
  content: string;
  created_at: string;
}

export interface ToolExecutionResponse {
  id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  status: "success" | "error";
  result_summary: string | null;
  duration_ms: number;
  error_message: string | null;
  created_at: string;
}

export type StreamEvent =
  | {
      type: "text_delta";
      text: string;
      conversation_id: string | null;
      message_id: string | null;
      usage: null;
      estimated_cost_usd: null;
      tool_name: null;
      tool_status: null;
    }
  | {
      type: "tool_call";
      text: null;
      conversation_id: string | null;
      message_id: string | null;
      usage: null;
      estimated_cost_usd: null;
      tool_name: string;
      tool_status: "success" | "error";
    }
  | {
      type: "done";
      text: null;
      conversation_id: string;
      message_id: string;
      usage: { input_tokens: number; output_tokens: number };
      estimated_cost_usd: number;
      tool_name: null;
      tool_status: null;
    }
  | {
      type: "error";
      message: string;
    };

export interface TM1ChangeSummary {
  id: string;
  connection_id: string;
  change_type: ChangeType;
  target_name: string;
  status: ChangeStatus;
  new_content: Record<string, unknown> | null;
  previous_content: Record<string, unknown> | null;
  validation_errors: ProcessSyntaxError[] | null;
  impact: (RelatedObject | { note: string })[] | null;
  error_message: string | null;
  created_by: string;
  executed_by: string | null;
  created_at: string;
  executed_at: string | null;
  rolled_back_at: string | null;
}

export interface TM1ChangeDetail {
  change: TM1ChangeSummary;
  preview: {
    current: Record<string, unknown> | null;
    proposed: Record<string, unknown> | null;
    impact: (RelatedObject | { note: string })[] | null;
    validation_errors: ProcessSyntaxError[] | null;
  };
}
