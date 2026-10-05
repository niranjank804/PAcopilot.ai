/**
 * The Team pages: work items list, the team's activity, and one work item's
 * story — what is linked, what the timeline says, and records the viewer
 * cannot open shown without detail.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn(), push: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ ApiError: class extends Error {}, apiRequest: mocks.apiRequest }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
  useParams: () => ({ id: "w1" }),
}));

import TeamPage from "../team/page";
import WorkItemPage from "../team/[id]/page";

const ITEM = {
  id: "w1", reference: "PBI #1234", title: "Workforce load fails on the new year", description: null,
  status: "in_progress", root_cause: "Year has no 2027 element.", resolution: null, created_by: "u1",
  created_at: "2026-10-01T09:00:00Z", updated_at: "2026-10-02T09:00:00Z",
};

function renderWith(node: ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      {node}
    </QueryClientProvider>,
  );
}

describe("Team page", () => {
  it("lists work items, changes awaiting approval and shared conversations", async () => {
    mocks.apiRequest.mockImplementation(async (path: string) => {
      if (path.startsWith("/team/work-items")) return [ITEM];
      return {
        open_work_items: [ITEM],
        shared_conversations: [{ id: "c1", title: "Why did Load Sales fail?", owner_id: "u2",
          owner_name: "Asha Rao", created_at: ITEM.created_at, updated_at: ITEM.updated_at }],
        changes: [{ id: "ch1", connection_id: "k1", connection_name: "Dev server", environment: "dev",
          change_type: "update_rules", target_name: "Workforce", status: "draft", awaiting_approval: true,
          created_at: ITEM.created_at, executed_at: null, created_by_name: "Asha Rao" }],
        health: [],
      };
    });
    renderWith(<TeamPage />);

    expect(await screen.findByText("PBI #1234")).toBeInTheDocument();
    expect(await screen.findByText("Why did Load Sales fail?")).toBeInTheDocument();
    expect(screen.getByText("Workforce").closest("a")).toHaveAttribute(
      "href", "/deployments?connection=k1&change=ch1",
    );
  });

  it("filters work items by status", async () => {
    mocks.apiRequest.mockImplementation(async (path: string) =>
      path.startsWith("/team/work-items") ? [] : { open_work_items: [], shared_conversations: [], changes: [], health: [] },
    );
    const user = userEvent.setup();
    renderWith(<TeamPage />);

    await user.click(await screen.findByRole("button", { name: "Resolved" }));
    expect(mocks.apiRequest).toHaveBeenCalledWith("/team/work-items?status=resolved");
  });
});

describe("Work item page", () => {
  it("shows progress, linked records and the timeline; a hidden record has no detail", async () => {
    mocks.apiRequest.mockResolvedValue({
      item: ITEM,
      created_by_name: "Asha Rao",
      progress: [
        { key: "investigation", label: "Investigation", done: true },
        { key: "approval", label: "Approval", done: false },
      ],
      links: [
        { link_id: "l1", kind: "change", target_id: "ch1", available: true, title: "update rules · Workforce",
          note: null, linked_at: ITEM.created_at, linked_by_name: "Asha Rao", owner_name: null, messages: null,
          status: "executed", connection_id: "k1", connection_name: "Dev server", environment: "dev" },
        { link_id: "l2", kind: "change", target_id: "ch2", available: false,
          title: "A change on a TM1 connection you cannot use", note: null, linked_at: ITEM.created_at,
          linked_by_name: "Ben Lee", owner_name: null, messages: null, status: null, connection_id: null,
          connection_name: null, environment: null },
      ],
      events: [
        { at: ITEM.created_at, kind: "created", title: "PBI #1234 opened", detail: ITEM.title, actor: "Asha Rao", link_id: null },
        { at: ITEM.updated_at, kind: "change_deployed", title: "Applied — update rules · Workforce",
          detail: "Dev server (DEV)", actor: "Ben Lee", link_id: "l1" },
      ],
    });
    renderWith(<WorkItemPage />);

    expect(await screen.findByText("Applied — update rules · Workforce")).toBeInTheDocument();
    expect(screen.getByText("update rules · Workforce").closest("a")).toHaveAttribute(
      "href", "/deployments?connection=k1&change=ch1",
    );
    const hidden = screen.getByText("A change on a TM1 connection you cannot use");
    expect(hidden.closest("a")).toBeNull();
    expect(screen.getByDisplayValue("Year has no 2027 element.")).toBeInTheDocument();
    expect(screen.getByText("Approval").textContent).toContain("not yet");
  });
});

const INCIDENT = {
  ...ITEM, id: "w1", reference: "INC-42", title: "Production allocation is wrong", kind: "incident",
  severity: "high", connection_id: "k9", cube_name: "Allocation", process_name: null,
};

function incidentDetail(investigations: unknown) {
  return {
    item: INCIDENT, created_by_name: "Asha Rao", progress: [], links: [], events: [], investigations,
  };
}

const LOOK = {
  id: "i1", created_at: "2026-10-05T09:00:00Z", window_hours: 48, summary: "2 suspect(s)",
  findings: {
    summary: "2 suspect(s) in the last 48 h on Planning PROD (PROD). Most likely: Applied: update rules on Allocation.",
    environment: "prod", connection: "Planning PROD", window_hours: 48,
    affected: { cubes: ["Allocation"], rule_sources: ["Rates"], writers: { Allocation: ["Load Allocation"] }, reported_process: null },
    suspects: [
      { score: 90, kind: "change", title: "Applied: update rules on Allocation", detail: "Applied by Ben Lee",
        at: "2026-10-05T07:00:00Z", mitigation: { action: "rollback", label: "Roll back this change (update rules on Allocation)", change_id: "ch7" } },
      { score: 75, kind: "run_failed", title: "Load Allocation last ended 'aborted'", detail: null, at: null,
        mitigation: { action: "diagnose", label: "Diagnose Load Allocation, fix it, then draft a re-run", process: "Load Allocation" } },
    ],
    evidence: { changes: [], runs: [], model_extractions: 0, open_alerts: 0 },
    notes: [], applied_nothing: "This investigation only read. Every mitigation is a change a person approves.",
  },
};

describe("Incident page", () => {
  it("ranks the suspects and links each mitigation to a governed action", async () => {
    mocks.apiRequest.mockResolvedValue(incidentDetail([LOOK]));
    const user = userEvent.setup();
    renderWith(<WorkItemPage />);

    expect(await screen.findByText("Applied: update rules on Allocation")).toBeInTheDocument();
    expect(screen.getByText("most likely")).toBeInTheDocument();
    expect(screen.getByText(/Roll back this change/).closest("a")).toHaveAttribute(
      "href", "/deployments?connection=k9&change=ch7",
    );
    expect(screen.getByText(/Diagnose Load Allocation/)).toBeInTheDocument();
    expect(screen.getByText(/Every mitigation is a change a person approves/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Investigate again/ }));
    expect(mocks.apiRequest).toHaveBeenCalledWith("/team/work-items/w1/investigate", { method: "POST" });
  });

  it("hides the findings from someone who cannot use the server", async () => {
    mocks.apiRequest.mockResolvedValue(incidentDetail(null));
    renderWith(<WorkItemPage />);

    expect(await screen.findByText(/Hidden: you cannot use this TM1 server/)).toBeInTheDocument();
  });
});
