/**
 * The Engineering Memory page: the assistant's suggestions wait for a
 * person, approved memory is listed as in use.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ ApiError: class extends Error {}, apiRequest: mocks.apiRequest }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import MemoryPage from "../memory/page";

const PROPOSAL = {
  id: "p1", kind: "caution", text: "Do not change the Margin rule without the controller.",
  status: "proposed", source: "ai", version: 1, object_type: "rule", object_name: "Margin",
  rationale: "The user said so.", decided_at: null, created_at: "2026-10-03T10:00:00Z",
};
const APPROVED = { ...PROPOSAL, id: "a1", text: "Load Rates runs before Load Sales.", status: "approved",
  source: "human", kind: "sequence", object_type: "process", object_name: "Load Sales", rationale: null };

describe("Engineering Memory page", () => {
  it("shows AI suggestions waiting for approval and approves on click", async () => {
    mocks.apiRequest.mockImplementation(async (path: string, options?: { method?: string }) => {
      if (options?.method === "POST") return {};
      return path.includes("status=proposed") ? [PROPOSAL] : [APPROVED];
    });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText(PROPOSAL.text)).toBeInTheDocument();
    expect(screen.getByText("suggested by the assistant")).toBeInTheDocument();
    expect(screen.getByText("Why: The user said so.")).toBeInTheDocument();
    expect(await screen.findByText(APPROVED.text)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Approve/ }));
    expect(mocks.apiRequest).toHaveBeenCalledWith("/knowledge/memory/p1/approve", { method: "POST" });
  });
});
