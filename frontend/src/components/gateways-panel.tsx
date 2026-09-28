"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Download, KeyRound, Network, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, apiRequest } from "@/lib/api-client";
import {
  GATEWAY_DOWNLOAD,
  GATEWAY_EXE,
  setupCommands,
  type GatewayKey,
  type TM1Gateway,
} from "@/lib/gateways";

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong.";
}

function lastSeen(gateway: TM1Gateway): string {
  if (!gateway.last_seen_at) return "never connected";
  const minutes = Math.round((Date.now() - Date.parse(gateway.last_seen_at)) / 60_000);
  return minutes < 1 ? "seen just now" : `seen ${minutes} min ago`;
}

/**
 * Gateways: how PA-Copilot reaches TM1 servers inside company networks.
 *
 * A TM1 server on a private network cannot be reached from the cloud; a
 * gateway installed once inside that network connects out and carries the
 * requests. Its key is shown once, with the exact commands to install it.
 */
export function GatewaysPanel() {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [issued, setIssued] = useState<GatewayKey | null>(null);
  const [target, setTarget] = useState("localhost:8010");

  const gatewaysQuery = useQuery({
    queryKey: ["tm1-gateways"],
    queryFn: () => apiRequest<TM1Gateway[]>("/tm1/gateways"),
    // Online/offline changes as gateways connect; keep the badge honest.
    refetchInterval: 30_000,
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["tm1-gateways"] });
  };

  const createMutation = useMutation({
    mutationFn: () =>
      apiRequest<GatewayKey>("/tm1/gateways", { method: "POST", body: { name: name.trim() } }),
    onSuccess: (key) => {
      setCreateOpen(false);
      setName("");
      setIssued(key);
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const rotateMutation = useMutation({
    mutationFn: (gateway: TM1Gateway) =>
      apiRequest<GatewayKey>(`/tm1/gateways/${gateway.id}/rotate-key`, { method: "POST" }),
    onSuccess: (key) => {
      setIssued(key);
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const deleteMutation = useMutation({
    mutationFn: (gateway: TM1Gateway) =>
      apiRequest<unknown>(`/tm1/gateways/${gateway.id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Gateway removed.");
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const gateways = gatewaysQuery.data ?? [];

  return (
    <Card data-testid="gateways-panel">
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
        <div className="min-w-0">
          <CardTitle className="flex items-center gap-2 text-lg">
            <Network className="h-5 w-5" />
            Gateways
          </CardTitle>
          <CardDescription>
            For TM1 servers inside a company network. Install a gateway once
            per network — on any always-on machine that can reach TM1 — and
            every user reaches those servers from here. It connects out, so no
            firewall port is opened.
          </CardDescription>
        </div>
        <Button variant="outline" size="sm" onClick={() => setCreateOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          Add gateway
        </Button>
      </CardHeader>
      <CardContent className="space-y-2">
        {gateways.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No gateways yet. Add one if your TM1 server is on a private network
            (an address like 192.168.x.x or a server name only your network knows).
          </p>
        ) : (
          gateways.map((gateway) => (
            <div
              key={gateway.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{gateway.name}</span>
                  <Badge variant={gateway.online ? "success" : "secondary"}>
                    {gateway.online ? "online" : "offline"}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground">
                  {[
                    gateway.hostname,
                    gateway.version ? `v${gateway.version}` : null,
                    lastSeen(gateway),
                    `${gateway.connection_count} connection(s)`,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </div>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => rotateMutation.mutate(gateway)}
                  disabled={rotateMutation.isPending}
                >
                  <KeyRound className="mr-2 h-4 w-4" />
                  New key
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="text-destructive"
                  onClick={() => deleteMutation.mutate(gateway)}
                  disabled={deleteMutation.isPending}
                  aria-label={`Remove gateway ${gateway.name}`}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ))
        )}
      </CardContent>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Add a gateway</DialogTitle>
            <DialogDescription>
              Name it after the network it serves, e.g. &ldquo;Head office&rdquo;.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="gateway-name">Name</Label>
            <Input
              id="gateway-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Head office"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => createMutation.mutate()}
              disabled={!name.trim() || createMutation.isPending}
            >
              {createMutation.isPending ? "Creating…" : "Create gateway"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={issued !== null} onOpenChange={(open) => !open && setIssued(null)}>
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Install &ldquo;{issued?.gateway.name}&rdquo;</DialogTitle>
            <DialogDescription>
              The key is shown only now. Copy the commands before closing — a
              lost key can be replaced with &ldquo;New key&rdquo;.
            </DialogDescription>
          </DialogHeader>
          {issued ? (
            <ol className="space-y-4 text-sm">
              <li className="space-y-2">
                <p className="font-medium">
                  1. On a Windows machine in that network, download the gateway.
                </p>
                <a
                  href={GATEWAY_DOWNLOAD}
                  download
                  className="inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm font-medium hover:bg-muted"
                >
                  <Download className="h-4 w-4" />
                  pa-copilot-gateway.zip
                </a>
                <p className="text-xs text-muted-foreground">
                  If the browser asks, choose &ldquo;Keep&rdquo;. Then right-click the
                  zip, &ldquo;Extract All&rdquo;, and open the extracted folder &mdash;
                  it holds {GATEWAY_EXE}.
                </p>
              </li>
              <li className="space-y-2">
                <p className="font-medium">
                  2. The TM1 server it may reach — the address as that machine
                  sees it, and TM1&rsquo;s HTTPPortNumber.
                </p>
                <Input
                  value={target}
                  onChange={(event) => setTarget(event.target.value)}
                  aria-label="TM1 server and port"
                  className="max-w-xs"
                />
              </li>
              <li className="space-y-2">
                <p className="font-medium">
                  3. In a Command Prompt opened as Administrator, in the extracted
                  folder, run:
                </p>
                {setupCommands(issued, target.trim() || "localhost:8010").map((command) => (
                  <CommandLine key={command} command={command} />
                ))}
                <p className="text-xs text-muted-foreground">
                  <code>test</code> checks PA-Copilot and TM1 answer;{" "}
                  <code>install</code> starts the gateway with Windows. It shows
                  here as online within a minute.
                </p>
              </li>
              <li>
                <p className="font-medium">
                  4. Create a Native connection with the TM1 address as that
                  machine sees it, and choose this gateway under &ldquo;Reached
                  through&rdquo;.
                </p>
              </li>
            </ol>
          ) : null}
          <DialogFooter>
            <Button onClick={() => setIssued(null)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

function CommandLine({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);

  return (
    <div className="flex items-start gap-2 rounded-md bg-muted p-2">
      <code className="min-w-0 flex-1 break-all font-mono text-xs">{command}</code>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="h-7 shrink-0 px-2"
        aria-label="Copy command"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(command);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          } catch {
            toast.error("Couldn't copy — select the text instead.");
          }
        }}
      >
        {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      </Button>
    </div>
  );
}
