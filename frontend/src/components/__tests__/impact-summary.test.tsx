/**
 * Impact is read severity-first, and a change that reaches critical or high
 * objects cannot be applied until the approver confirms reading it.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }));

vi.mock("@/lib/api-client", () => ({
  ApiError: class extends Error {},
  apiRequest: mocks.apiRequest,
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import { ChangeActionCard } from "../change-action-card";
import { ImpactSummary, needsAcknowledgement, type ImpactEntry } from "../impact-summary";

const IMPACT: ImpactEntry[] = [
  { object_type: "chore", name: "Nightly", severity: "critical", reason: "runs it on a schedule 'Load'" },
  { object_type: "cube", name: "Sales", severity: "medium", reason: "its data are written by this process" },
  { note: "The dependency map is 9 days old." },
];

describe("ImpactSummary", () => {
  it("counts by severity, writes severity out, and keeps notes", () => {
    render(<ImpactSummary entries={IMPACT} />);

    expect(screen.getByText("Critical: 1")).toBeInTheDocument();
    expect(screen.getByText("High: 0")).toBeInTheDocument();
    expect(screen.getByText("Medium: 1")).toBeInTheDocument();
    expect(screen.getByText(/runs it on a schedule/)).toBeInTheDocument();
    expect(screen.getByText(/9 days old/)).toBeInTheDocument();
  });

  it("needs confirming only for critical or high", () => {
    expect(needsAcknowledgement(IMPACT)).toBe(true);
    expect(needsAcknowledgement([IMPACT[1], IMPACT[2]])).toBe(false);
  });
});

describe("ChangeActionCard approval", () => {
  beforeEach(() => mocks.apiRequest.mockReset());

  it("keeps Execute disabled until a serious impact is confirmed, and sends the confirmation", async () => {
    const user = userEvent.setup();
    const change = {
      id: "c1", connection_id: "k1", change_type: "delete_process", target_name: "Load",
      status: "draft", new_content: null, previous_content: null, validation_errors: null,
      impact: IMPACT, error_message: null, superseded_by: null, created_by: "u1",
      executed_by: null, created_at: "", executed_at: null, rolled_back_at: null,
    };
    mocks.apiRequest.mockImplementation(async (path: string, options?: { method?: string }) =>
      options?.method === "POST" ? { ...change, status: "executed" } : { change, preview: {} },
    );

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ChangeActionCard connectionId="k1" changeId="c1" />
      </QueryClientProvider>,
    );

    await user.click(await screen.findByRole("button", { name: /Execute on server/ }));
    const dialog = await screen.findByRole("alertdialog");
    const execute = within(dialog).getByRole("button", { name: "Execute" });

    expect(execute).toBeDisabled();
    await user.click(within(dialog).getByRole("checkbox"));
    expect(execute).toBeEnabled();
    await user.click(execute);

    expect(mocks.apiRequest).toHaveBeenCalledWith(
      "/tm1/connections/k1/changes/c1/execute",
      { method: "POST", body: { acknowledge_impact: true } },
    );
  });
});
