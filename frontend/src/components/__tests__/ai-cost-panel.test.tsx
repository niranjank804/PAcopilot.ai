import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ apiRequest: mocks.apiRequest, ApiError: class extends Error {} }));

import { AICostPanel } from "../ai-cost-panel";

describe("AICostPanel", () => {
  it("shows spend, savings with the AUTO estimate labelled, and spend by agent", async () => {
    mocks.apiRequest.mockResolvedValue({
      days: 30, requests: 40, total_cost_usd: 3.25, cost_per_request_usd: 0.0812, tool_calls: 120,
      avg_latency_ms: 6400, p95_latency_ms: 21000, fallback_rate: 0.025,
      by_agent: [{ name: "developer", requests: 20, cost_usd: 2.1, cost_per_request_usd: 0.105 }],
      by_tier: [], by_user: [],
      cache_savings_usd: 0.84,
      auto_routing: { requests: 30, estimated_savings_usd: 4.4,
                      assumption: "Estimated as the same tokens priced at the BEST model." },
      notes: [],
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><AICostPanel /></QueryClientProvider>);

    expect(await screen.findByText("$3.25")).toBeInTheDocument();
    expect(screen.getByText("Saved by AUTO (estimate)")).toBeInTheDocument();
    expect(screen.getByText(/priced at the BEST model/)).toBeInTheDocument();
    expect(screen.getByText("developer")).toBeInTheDocument();
    expect(screen.getByText("2.5%")).toBeInTheDocument();
  });
});
