/**
 * The Command Center: each section from one read, links to where to act,
 * and a plain prompt when no server is connected.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ apiRequest: mocks.apiRequest }));

import { CommandCenter, type CommandCenterData } from "../command-center";

const SERVER = { connection_id: "k1", connection_name: "Planning DEV", environment: "dev" as const };
const DATA: CommandCenterData = {
  servers: 1,
  health: [{ ...SERVER, score: 58, grade: "D", scanned_at: "2026-10-06T06:00:00Z" }],
  risks: [{ category: "failed_processes", label: "Processes that failed", count: 3, points: 6, servers: ["Planning DEV"] }],
  incidents: [{ id: "w1", reference: "INC-7", title: "Allocation is wrong", severity: "high", status: "open" }],
  failed_processes: [{ ...SERVER, process: "Load Sales", failed_runs_7_days: 2, last_failed_at: "2026-10-06T05:00:00Z" }],
  regressions: [{ ...SERVER, process: "Load Rates", summary: "Load Rates normally runs in 40 s; latest 3 min." }],
  alerts: { open: 1, critical: 1, latest: [{ ...SERVER, id: "a1", title: "Load Sales aborted", severity: "critical" }] },
  pending_approvals: [{ ...SERVER, id: "c1", change_type: "update_rules", target_name: "Sales", status: "draft",
    created_at: "2026-10-06T04:00:00Z", executed_at: null, rolled_back_at: null, by: "Asha Rao" }],
  deployments: [],
  model_changes: [],
  ai: { days: 30, requests: 120, cost_usd: 4.5, avg_latency_ms: 8200 },
};

function renderIt() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <CommandCenter />
    </QueryClientProvider>,
  );
}

describe("CommandCenter", () => {
  it("shows what needs attention and links to where to act", async () => {
    mocks.apiRequest.mockResolvedValue(DATA);
    renderIt();

    expect(await screen.findByText("INC-7")).toBeInTheDocument();
    expect(screen.getByText("58 · D")).toBeInTheDocument();
    expect(screen.getByText("Processes that failed: 3 (−6 pts)")).toBeInTheDocument();
    expect(screen.getByText("Load Sales aborted")).toBeInTheDocument();
    expect(screen.getByText("update rules · Sales").closest("a")).toHaveAttribute(
      "href", "/deployments?connection=k1&change=c1",
    );
    expect(screen.getByText("Load Rates normally runs in 40 s; latest 3 min.")).toBeInTheDocument();
    expect(screen.getByText("$4.50")).toBeInTheDocument();
  });

  it("asks for a connection when there is none", async () => {
    mocks.apiRequest.mockResolvedValue({ ...DATA, servers: 0 });
    renderIt();

    expect(await screen.findByText("Connections")).toBeInTheDocument();
  });
});
