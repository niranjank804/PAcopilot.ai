/**
 * The Alerts page: what the rules found, the assistant's suggestions
 * waiting to be turned on, and a plain notice when email is not set up.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ ApiError: class extends Error {}, apiRequest: mocks.apiRequest }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import AlertsPage from "../alerts/page";

const RULE = {
  id: "r1", connection_id: "k1", name: "Alert when Workforce Planning takes more than 2x its 30-day average",
  kind: "performance_regression", params: { process_name: "Workforce Planning", factor: 2, window_days: 30 },
  status: "proposed", source: "ai", rationale: "Alert me if Workforce Planning exceeds 2x its 30-day average.",
  interval_minutes: 15, notify: [], last_checked_at: null, last_error: null, consecutive_errors: 0,
  created_by: "u1", created_at: "2026-10-05T09:00:00Z",
};
const ALERT = {
  id: "a1", rule_id: "r2", connection_id: "k1", severity: "critical", title: "Load Sales aborted",
  detail: "Finished 2026-10-05 08:00 UTC with outcome 'aborted'.", evidence: null,
  fired_at: "2026-10-05T08:01:00Z", status: "open", acknowledged_by: null, acknowledged_at: null, emailed: false,
};

function serve(emailConfigured: boolean) {
  mocks.apiRequest.mockImplementation(async (path: string, options?: { method?: string }) => {
    if (options?.method) return { ...RULE, status: "active" };
    if (path === "/monitoring/setup") {
      return { kinds: [{ kind: "process_failure", label: "A process fails" }], email_configured: emailConfigured,
        schedule_path: "/internal/cron/monitors" };
    }
    if (path.startsWith("/monitoring/alerts")) return path.includes("status=open") ? [ALERT] : [];
    if (path === "/monitoring/rules") return [RULE];
    if (path === "/tm1/connections") return [{ id: "k1", name: "Dev server", environment: "dev" }];
    return [];
  });
}

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AlertsPage />
    </QueryClientProvider>,
  );
}

describe("Alerts page", () => {
  it("shows open alerts and acknowledges one", async () => {
    serve(true);
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("Load Sales aborted")).toBeInTheDocument();
    expect(screen.getByText("critical")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Acknowledge" }));
    expect(mocks.apiRequest).toHaveBeenCalledWith("/monitoring/alerts/a1/acknowledge", { method: "POST" });
  });

  it("holds the assistant's rule until a person turns it on", async () => {
    serve(true);
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("Suggested by the assistant")).toBeInTheDocument();
    expect(screen.getByText(/You asked: Alert me if Workforce Planning/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Turn on/ }));
    expect(mocks.apiRequest).toHaveBeenCalledWith("/monitoring/rules/r1", {
      method: "PATCH",
      body: { status: "active" },
    });
  });

  it("says plainly when alerts cannot be emailed", async () => {
    serve(false);
    renderPage();

    expect(await screen.findByText(/Email is not set up on this deployment/)).toBeInTheDocument();
  });
});
