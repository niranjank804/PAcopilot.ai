import type { TM1Connection } from "@/lib/types";

/** A PA-Copilot gateway: installed once inside a company network, it
 *  carries TM1 requests to the TM1 servers there. */
export interface TM1Gateway {
  id: string;
  name: string;
  online: boolean;
  last_seen_at: string | null;
  version: string | null;
  hostname: string | null;
  created_at: string;
  /** Connections through this gateway the signed-in user can see. */
  connection_count: number;
  /** Other members' private connections through it, hidden from this user. */
  hidden_connection_count?: number;
}

/** Returned once, when a gateway is created or its key rotated. */
export interface GatewayKey {
  gateway: TM1Gateway;
  key: string;
  server_url: string;
}

export type ConnectionWithGateway = TM1Connection & { gateway_id?: string | null };

/** How many connections, across every gateway, are another member's private
 *  ones: they exist but are not listed for this user. */
export function hiddenConnectionCount(gateways: TM1Gateway[] | undefined): number {
  return (gateways ?? []).reduce((n, g) => n + (g.hidden_connection_count ?? 0), 0);
}

/** Why a member sees no connection while a gateway has one. */
export function hiddenConnectionsNote(hidden: number): string {
  return hidden === 1
    ? "A gateway connection exists, but it is private to the member who added it. Ask them to share it with the organization (Edit → Who can use it → Everyone in my organization)."
    : `${hidden} gateway connections exist, but they are private to the members who added them. Ask them to share them with the organization (Edit → Who can use it → Everyone in my organization).`;
}

/** The form's value for "reached directly, no gateway". */
export const DIRECT = "direct";

/** Where the Windows gateway program is downloaded from (served by this site). */
export const GATEWAY_DOWNLOAD = "/downloads/pa-copilot-gateway.zip";
export const GATEWAY_EXE = "pa-copilot-gateway.exe";

/** The commands shown to whoever installs the gateway. */
export function setupCommands(key: GatewayKey, tm1Target: string): string[] {
  return [
    `${GATEWAY_EXE} setup --server ${key.server_url} --key ${key.key} --allow ${tm1Target}`,
    `${GATEWAY_EXE} test`,
    `${GATEWAY_EXE} install`,
  ];
}
