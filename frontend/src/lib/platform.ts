/** The Super Admin's platform view (backend: src/api/v1/platform.py). */

export interface PlatformPerson {
  id: string;
  name: string;
  email: string;
}

export interface PlatformOverview {
  organizations: number;
  users: number;
  active_users_24h: number;
  pending_signups: number;
  sign_ins_24h: number;
  failed_sign_ins_24h: number;
  connections: number;
  suspended_connections: number;
  api_requests_24h: number;
  failed_api_requests_24h: number;
  ai_requests_24h: number;
  ai_cost_24h: number;
}

export interface PlatformUser {
  id: string;
  username: string;
  email: string;
  name: string;
  organization_id: string;
  organization: string;
  roles: string[];
  registration_status: string;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
  last_seen_at: string | null;
  last_ip: string | null;
  connections_owned: number;
  connections_used_30d: number;
  ai_requests_30d: number;
  ai_cost_30d: number;
}

export interface PlatformConnection {
  id: string;
  organization_id: string;
  organization: string;
  name: string;
  address: string;
  port: number;
  ssl: boolean;
  authentication_type: string;
  tm1_user: string;
  tenant: string | null;
  database: string | null;
  environment: string;
  visibility: string;
  is_active: boolean;
  gateway: string | null;
  owner: PlatformPerson | null;
  created_at: string;
  last_used_at: string | null;
  used_by_30d: PlatformPerson[];
  suspended_at: string | null;
  suspended_reason: string | null;
  suspended_by: PlatformPerson | null;
}

export interface SignIn {
  id: string;
  at: string;
  method: string;
  success: boolean;
  identifier: string | null;
  reason: string | null;
  ip_address: string | null;
  user_agent: string | null;
  user: PlatformPerson | null;
  organization: string | null;
}

export interface AuditRow {
  id: string;
  at: string;
  action: string;
  entity: string;
  entity_id: string | null;
  connection: string | null;
  user: PlatformPerson | null;
  organization: string | null;
  details: Record<string, string>;
  ip_address: string | null;
  user_agent: string | null;
}

export interface ActivityEvent {
  kind: "action" | "tool";
  at: string;
  action: string;
  entity: string;
  connection: { id: string; name: string } | null;
  details: Record<string, string>;
  ip_address?: string | null;
  status?: string;
}

export interface RequestRow {
  id: string;
  at: string;
  method: string;
  path: string;
  route: string | null;
  status_code: number;
  duration_ms: number;
  ip_address: string | null;
  user_agent: string | null;
  user: PlatformPerson | null;
  organization: string | null;
  connection?: { id: string; name: string } | null;
}

export interface UserActivity {
  user: PlatformPerson & { is_active: boolean };
  days: number;
  events: ActivityEvent[];
  requests: RequestRow[];
  sign_ins: SignIn[];
}

/** "3 min ago", "2 h ago", "4 d ago", or the date. */
export function ago(value: string | null): string {
  if (!value) return "never";
  const seconds = (Date.now() - new Date(value).getTime()) / 1000;
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  if (seconds < 86400 * 30) return `${Math.floor(seconds / 86400)} d ago`;
  return new Date(value).toLocaleDateString();
}

/** The browser and system from a user-agent string, roughly. */
export function device(userAgent: string | null): string {
  if (!userAgent) return "—";
  const browser =
    /Edg\//.test(userAgent) ? "Edge"
    : /Chrome\//.test(userAgent) ? "Chrome"
    : /Firefox\//.test(userAgent) ? "Firefox"
    : /Safari\//.test(userAgent) ? "Safari"
    : "Other";
  const system =
    /Windows/.test(userAgent) ? "Windows"
    : /Android/.test(userAgent) ? "Android"
    : /iPhone|iPad/.test(userAgent) ? "iOS"
    : /Mac OS/.test(userAgent) ? "macOS"
    : /Linux/.test(userAgent) ? "Linux"
    : "";
  return system ? `${browser} · ${system}` : browser;
}

/** A CSV cell. Audit text comes from users (names, reasons, typed sign-in
 * names), so a value Excel would read as a formula is prefixed with an
 * apostrophe and shown as text instead of run. */
function csvField(value: unknown): string {
  let text = value === null || value === undefined ? "" : String(value);
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function auditCsv(rows: AuditRow[]): string {
  const header = ["Time", "Organization", "User", "Email", "Action", "Entity", "Connection", "Details", "IP"];
  const lines = rows.map((r) => [
    r.at, r.organization, r.user?.name, r.user?.email, r.action, r.entity, r.connection,
    Object.entries(r.details).map(([k, v]) => `${k}=${v}`).join("; "), r.ip_address,
  ]);
  return [header, ...lines].map((line) => line.map(csvField).join(",")).join("\r\n");
}
