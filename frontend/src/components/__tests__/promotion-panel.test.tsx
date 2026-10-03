/**
 * Promotion is offered only for an applied change, one environment up, and
 * the package shows the road the change took.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }));

vi.mock("@/lib/api-client", () => ({
  ApiError: class extends Error {},
  apiRequest: mocks.apiRequest,
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import type { TM1ChangeSummary, TM1Connection } from "@/lib/types";

import { PromotionPanel } from "../promotion-panel";

const base = {
  name: "", address: "x", port: 8010, ssl: true, username: "a", is_active: true,
  authentication_type: "native" as const, tenant: null, database: null,
};
const CONNECTIONS: TM1Connection[] = [
  { ...base, id: "dev1", name: "Dev box", environment: "dev" },
  { ...base, id: "qa1", name: "QA box", environment: "qa" },
  { ...base, id: "prod1", name: "Prod box", environment: "prod" },
];

function change(overrides: Partial<TM1ChangeSummary> = {}): TM1ChangeSummary {
  return {
    id: "c1", connection_id: "dev1", change_type: "update_rules", target_name: "Sales",
    status: "executed", new_content: { rules: "x" }, previous_content: null,
    validation_errors: null, impact: [], error_message: null, superseded_by: null,
    created_by: "u1", executed_by: "u2", created_at: "", executed_at: "", rolled_back_at: null,
    ...overrides,
  };
}

function renderPanel(c: TM1ChangeSummary, environment: "dev" | "qa" | "prod" = "dev", onPromoted = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <PromotionPanel change={c} connections={CONNECTIONS} environment={environment} onPromoted={onPromoted} />
    </QueryClientProvider>,
  );
  return onPromoted;
}

beforeEach(() => mocks.apiRequest.mockReset());

describe("PromotionPanel", () => {
  it("promotes an applied DEV change to the QA connection", async () => {
    const user = userEvent.setup();
    mocks.apiRequest.mockResolvedValue(change({ id: "c2", connection_id: "qa1", status: "draft" }));
    const onPromoted = renderPanel(change());

    await user.click(screen.getByRole("button", { name: /Promote to QA \(QA box\)/ }));

    expect(mocks.apiRequest).toHaveBeenCalledWith(
      "/tm1/connections/dev1/changes/c1/promote",
      { method: "POST", body: { target_connection_id: "qa1" } },
    );
    expect(onPromoted).toHaveBeenCalledWith("qa1", "c2");
  });

  it("offers no promotion for a draft, a run, or a PROD change", () => {
    renderPanel(change({ status: "draft" }));
    renderPanel(change({ change_type: "run_process" }));
    renderPanel(change({ connection_id: "prod1" }), "prod");

    expect(screen.queryByRole("button", { name: /Promote/ })).not.toBeInTheDocument();
  });

  it("shows the road the change took in its package", async () => {
    const user = userEvent.setup();
    mocks.apiRequest.mockResolvedValue({
      manifest: { change_type: "update_rules", object: "Sales", target_connection: "Prod box",
                  target_environment: "PROD", content_sha256: "abc" },
      stages: [
        { change_id: "a", environment: "DEV", connection: "Dev box", status: "executed", requested_by: "Ann",
          requested_at: "", approved_by: "Ann", approved_at: "2026-10-01T10:00:00Z", verified: true, same_content: true },
        { change_id: "b", environment: "PROD", connection: "Prod box", status: "draft", requested_by: "Ann",
          requested_at: "", approved_by: null, approved_at: null, verified: false, same_content: true },
      ],
      evidence: { verified_in: ["DEV"], content_unchanged_since_first_stage: true, checks_here: [] },
      impact: [],
      approval_rule: "Needs the 'tm1.deploy.prod' permission, and someone other than the requester.",
      rollback_plan: "Roll back restores them.",
    });
    renderPanel(change({ status: "draft", connection_id: "prod1" }), "prod");

    await user.click(screen.getByRole("button", { name: /Deployment package/ }));

    expect(await screen.findByText(/Verified in DEV/)).toBeInTheDocument();
    expect(screen.getByText(/someone other than the requester/)).toBeInTheDocument();
    expect(screen.getByText(/not approved yet/)).toBeInTheDocument();
  });
});
