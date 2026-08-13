/**
 * Reports — where a person causes Excel to run on a customer's machine.
 *
 * Tested from the user's side. The cases that matter most are not the
 * happy path: that a duplicate-suppressed run reads as success rather
 * than as a mysterious no-op, and that a refusal from the server (no
 * capable worker, missing permission) is actually shown instead of
 * leaving the user staring at an unchanged screen.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
  class FakeApiError extends Error {
    constructor(
      public status: number,
      public code: string,
      message: string,
    ) {
      super(message);
    }
  }

  return {
    FakeApiError,
    apiRequest: vi.fn(),
    toastSuccess: vi.fn(),
    toastError: vi.fn(),
  };
});

vi.mock("@/lib/api-client", () => ({
  ApiError: mocks.FakeApiError,
  apiRequest: mocks.apiRequest,
  registerTokenAccessors: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: mocks.toastSuccess, error: mocks.toastError },
}));

import ReportsPage from "../page";

const REPORT = {
  id: "11111111-1111-1111-1111-111111111111",
  name: "Monthly P&L",
  description: null,
  report_type: "pafe_workbook",
  workbook_id: "22222222-2222-2222-2222-222222222222",
  connection_id: null,
  worker_id: null,
  output_formats: ["xlsx"],
  parameters: null,
  status: "active",
  approval_status: "not_required",
  created_at: "2026-08-13T10:00:00Z",
  updated_at: "2026-08-13T10:00:00Z",
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <ReportsPage />
    </QueryClientProvider>,
  );
}

function routeApi(overrides: Record<string, unknown> = {}) {
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path === "/reports/definitions") {
      return Promise.resolve(overrides.reports ?? [REPORT]);
    }

    if (path === "/reports/workbooks") {
      return Promise.resolve(overrides.workbooks ?? []);
    }

    return Promise.resolve(null);
  });
}

beforeEach(() => {
  // mockReset, not clearAllMocks: an unconsumed mockResolvedValueOnce
  // survives clearAllMocks and is then eaten by the *next* test's first
  // call, which silently returns the wrong shape and fails somewhere
  // unrelated. Reset drops queued once-values too.
  mocks.apiRequest.mockReset();
  mocks.toastSuccess.mockReset();
  mocks.toastError.mockReset();
});

describe("Reports listing", () => {
  it("shows a report and its output formats", async () => {
    routeApi();

    renderPage();

    expect(await screen.findByText("Monthly P&L")).toBeInTheDocument();
    expect(screen.getByText("XLSX")).toBeInTheDocument();
  });

  it("tells the user when there are no reports yet", async () => {
    routeApi({ reports: [] });

    renderPage();

    expect(
      await screen.findByText(/no reports yet/i),
    ).toBeInTheDocument();
  });

  it("says runs never start on their own", async () => {
    // The governance promise the product makes. If scheduling ever
    // ships, this line must change deliberately rather than silently
    // become untrue.
    routeApi();

    renderPage();

    expect(
      await screen.findByText(/never start on their own/i),
    ).toBeInTheDocument();
  });
});

describe("Run now", () => {
  it("confirms when an execution is queued", async () => {
    mocks.apiRequest.mockImplementation((path: string) => {
      if (path === "/reports/definitions") return Promise.resolve([REPORT]);
      if (path === "/reports/workbooks") return Promise.resolve([]);

      return Promise.resolve({ execution: { id: "exec-1" }, created: true });
    });

    const user = userEvent.setup();

    renderPage();

    await user.click(await screen.findByRole("button", { name: /run now/i }));

    await waitFor(() =>
      expect(mocks.apiRequest).toHaveBeenCalledWith(
        `/reports/definitions/${REPORT.id}/run`,
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("treats a duplicate-suppressed run as success, not failure", async () => {
    // The server returns created:false when an identical request in the
    // same minute already queued this report. Reporting that as an error
    // would train users to click again, which is exactly what the
    // idempotency key exists to prevent.
    routeApi();

    mocks.apiRequest.mockImplementation((path: string) => {
      if (path === "/reports/definitions") return Promise.resolve([REPORT]);
      if (path === "/reports/workbooks") return Promise.resolve([]);

      return Promise.resolve({ execution: { id: "exec-1" }, created: false });
    });

    const user = userEvent.setup();

    renderPage();

    await user.click(await screen.findByRole("button", { name: /run now/i }));

    await waitFor(() => expect(mocks.toastSuccess).toHaveBeenCalled());
    expect(mocks.toastError).not.toHaveBeenCalled();

    const message = mocks.toastSuccess.mock.calls.at(-1)?.[0] as string;

    expect(message).toMatch(/already queued/i);
  });

  it("surfaces a refusal when no worker can run the report", async () => {
    // The real server response when PAfE is not installed anywhere.
    // Silently swallowing it leaves the user with an unchanged screen
    // and no idea why nothing happened.
    routeApi();

    mocks.apiRequest.mockImplementation((path: string) => {
      if (path === "/reports/definitions") return Promise.resolve([REPORT]);
      if (path === "/reports/workbooks") return Promise.resolve([]);

      return Promise.reject(
        new mocks.FakeApiError(
          409,
          "WORKER_CAPABILITY_MISSING",
          "No worker is able to run this report.",
        ),
      );
    });

    const user = userEvent.setup();

    renderPage();

    await user.click(await screen.findByRole("button", { name: /run now/i }));

    await waitFor(() =>
      expect(mocks.toastError).toHaveBeenCalledWith(
        "No worker is able to run this report.",
      ),
    );
  });

  it("surfaces a permission refusal", async () => {
    routeApi();

    mocks.apiRequest.mockImplementation((path: string) => {
      if (path === "/reports/definitions") return Promise.resolve([REPORT]);
      if (path === "/reports/workbooks") return Promise.resolve([]);

      return Promise.reject(
        new mocks.FakeApiError(
          403,
          "PERMISSION_DENIED",
          "Missing permission: reports.execute",
        ),
      );
    });

    const user = userEvent.setup();

    renderPage();

    await user.click(await screen.findByRole("button", { name: /run now/i }));

    await waitFor(() =>
      expect(mocks.toastError).toHaveBeenCalledWith(
        "Missing permission: reports.execute",
      ),
    );
  });
});

describe("Developer preview labelling", () => {
  it("marks the feature as a preview", async () => {
    // PAfE has never been validated end-to-end. The badge is the only
    // thing telling a user not to depend on this yet.
    routeApi();

    renderPage();

    expect(
      await screen.findByText(/developer preview/i),
    ).toBeInTheDocument();
  });
});
