/**
 * The Model Health page shows the score, every point taken off with what
 * cost it, and slowdowns in plain words.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }));

vi.mock("@/lib/api-client", () => ({
  ApiError: class extends Error {},
  apiRequest: mocks.apiRequest,
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import HealthPage from "../health/page";

describe("Model Health page", () => {
  it("shows the score, the deductions with evidence, and regressions", async () => {
    mocks.apiRequest.mockImplementation(async (path: string) =>
      path === "/tm1/connections"
        ? [{ id: "k1", name: "devon", environment: "dev" }]
        : {
            latest: {
              scanned_at: "2026-10-03T03:30:00Z",
              score: 84,
              grade: "B",
              trigger: "schedule",
              totals: { notes: [] },
              deductions: [
                { category: "critical_rule_findings", label: "Critical rule findings", count: 1, points: 10,
                  points_each: 10, cap: 40, evidence: ["cube Sales: 1"] },
                { category: "rule_warnings", label: "Rule warnings", count: 0, points: 0,
                  points_each: 2, cap: 15, evidence: [] },
              ],
            },
            trend: [{ scanned_at: "2026-10-03T03:30:00Z", score: 84, grade: "B", trigger: "schedule" }],
            performance: {
              rule: "A regression is …",
              runs_known: 120,
              regressions: [{ process: "Workforce Load", increase_percent: 938,
                summary: "Workforce Load normally runs in 42 s (median of 12 runs). Latest run: 7 min 18 s. Regression: +938%." }],
              slowest: [{ process: "Workforce Load", median_seconds: 42, runs: 13 }],
              failures_7_days: [],
              not_covered: ["Memory and CPU per process"],
            },
          },
    );

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <HealthPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("84")).toBeInTheDocument();
    expect(screen.getByText("Grade B")).toBeInTheDocument();
    expect(screen.getByText("Critical rule findings: 1")).toBeInTheDocument();
    expect(screen.getByText("cube Sales: 1")).toBeInTheDocument();
    // Categories that cost nothing are not listed.
    expect(screen.queryByText(/Rule warnings/)).not.toBeInTheDocument();
    expect(screen.getByText(/Regression: \+938%/)).toBeInTheDocument();
  });
});
