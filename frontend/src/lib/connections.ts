import { apiRequest } from "@/lib/api-client";
import type { TM1Connection } from "@/lib/types";

/**
 * Connections the signed-in user may work with: their own and shared ones.
 *
 * The server decides what a user may see (backend src/tm1/service.py); this
 * only leaves out connections an organization admin can see and manage but
 * not use — a member's private one — so a picker never offers a server
 * every action on would refuse. Its own query key, because the Connections
 * page caches the full list under ["tm1-connections"].
 */
export const USABLE_CONNECTIONS_KEY = ["tm1-connections", "usable"] as const;

export async function fetchUsableConnections(): Promise<TM1Connection[]> {
  const connections = await apiRequest<TM1Connection[]>("/tm1/connections");
  return connections.filter((c) => c.can_use !== false);
}
