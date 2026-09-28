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
  connection_count: number;
}

/** Returned once, when a gateway is created or its key rotated. */
export interface GatewayKey {
  gateway: TM1Gateway;
  key: string;
  server_url: string;
}

export type ConnectionWithGateway = TM1Connection & { gateway_id?: string | null };

/** The form's value for "reached directly, no gateway". */
export const DIRECT = "direct";

/** Where the Windows gateway program is downloaded from (served by this site). */
export const GATEWAY_DOWNLOAD = "/downloads/pa-copilot-gateway.exe";
export const GATEWAY_EXE = "pa-copilot-gateway.exe";

/** The commands shown to whoever installs the gateway. */
export function setupCommands(key: GatewayKey, tm1Target: string): string[] {
  return [
    `${GATEWAY_EXE} setup --server ${key.server_url} --key ${key.key} --allow ${tm1Target}`,
    `${GATEWAY_EXE} test`,
    `${GATEWAY_EXE} install`,
  ];
}
