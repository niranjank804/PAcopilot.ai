/**
 * The model map says when it was read and what changed between reads —
 * and warns when it is too old to trust.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }));

vi.mock("@/lib/api-client", () => ({
  ApiError: class extends Error {},
  apiRequest: mocks.apiRequest,
}));

import { ModelHistory, type ExtractionRecord } from "../model-history";

function record(overrides: Partial<ExtractionRecord> = {}): ExtractionRecord {
  return {
    id: "e1",
    trigger: "schedule",
    status: "succeeded",
    started_at: new Date().toISOString(),
    object_count: 120,
    relationship_count: 340,
    unresolved_references: 0,
    error_message: null,
    changes: {
      first: false,
      counts: { objects_added: 1, objects_removed: 0, relationships_added: 1, relationships_removed: 0 },
      objects_added: [{ type: "process", name: "Load Forecast" }],
      objects_removed: [],
      relationships_added: [{ from: "process:Load Forecast", relationship: "updates_cube", to: "cube:Sales" }],
      relationships_removed: [],
    },
    ...overrides,
  };
}

function renderHistory() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ModelHistory connectionId="k1" onExtract={vi.fn()} extracting={false} />
    </QueryClientProvider>,
  );
}

beforeEach(() => mocks.apiRequest.mockReset());

describe("ModelHistory", () => {
  it("shows when the model was read and what changed", async () => {
    mocks.apiRequest.mockResolvedValue([record()]);
    renderHistory();

    expect(await screen.findByText(/120 objects, 340 dependencies/)).toBeInTheDocument();
    expect(screen.getByText("process Load Forecast")).toBeInTheDocument();
    expect(screen.getByText("Load Forecast updates cube Sales")).toBeInTheDocument();
    expect(screen.queryByText(/days old/)).not.toBeInTheDocument();
  });

  it("warns when the map is more than a week old", async () => {
    const old = new Date(Date.now() - 12 * 86_400_000).toISOString();
    mocks.apiRequest.mockResolvedValue([record({ started_at: old })]);
    renderHistory();

    expect(await screen.findByText(/answers may miss recent changes/)).toBeInTheDocument();
  });

  it("says plainly when the model has never been read", async () => {
    mocks.apiRequest.mockResolvedValue([]);
    renderHistory();

    expect(await screen.findByText(/Not read from TM1 yet/)).toBeInTheDocument();
  });
});
