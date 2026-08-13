/**
 * Report Workers — where a machine is granted the right to run reports.
 *
 * The cases that matter: an enrollment token is shown once and must be
 * visible enough to copy, a worker's *derived* status is displayed
 * rather than whatever it last claimed, and a host that failed its own
 * capability probe reads as unable rather than as fine.
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

import WorkersPage from "../page";

const ONLINE_WORKER = {
  id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  name: "finance-reporting-01",
  description: null,
  status: "online" as const,
  version: "0.1.0",
  os: "Windows 11",
  excel_version: "16.0",
  pafe_version: "2.0.99.1",
  hostname: "FIN-01",
  capabilities: ["excel", "pafe_automation", "xlsx_export"],
  last_heartbeat_at: new Date().toISOString(),
  enrolled_at: "2026-08-13T09:00:00Z",
  disabled_at: null,
  last_error: null,
  created_at: "2026-08-13T09:00:00Z",
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <WorkersPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.apiRequest.mockReset();
  mocks.toastSuccess.mockReset();
  mocks.toastError.mockReset();
});

describe("Worker listing", () => {
  it("shows host facts the operator needs", async () => {
    mocks.apiRequest.mockResolvedValue([ONLINE_WORKER]);

    renderPage();

    expect(await screen.findByText("finance-reporting-01")).toBeInTheDocument();
    expect(screen.getByText("2.0.99.1")).toBeInTheDocument();
    expect(screen.getByText("online")).toBeInTheDocument();
  });

  it("says PAfE is not detected rather than leaving it blank", async () => {
    // A blank cell reads as "loading" or "fine". This is the single most
    // common real condition and it must be unambiguous.
    mocks.apiRequest.mockResolvedValue([
      { ...ONLINE_WORKER, pafe_version: null, capabilities: ["excel"] },
    ]);

    renderPage();

    expect(await screen.findByText(/not detected/i)).toBeInTheDocument();
  });

  it("shows when a host verified no capabilities at all", async () => {
    mocks.apiRequest.mockResolvedValue([
      { ...ONLINE_WORKER, capabilities: [] },
    ]);

    renderPage();

    expect(await screen.findByText(/none verified/i)).toBeInTheDocument();
  });

  it("tells the user when no workers exist", async () => {
    mocks.apiRequest.mockResolvedValue([]);

    renderPage();

    expect(
      await screen.findByText(/no workers registered yet/i),
    ).toBeInTheDocument();
  });

  it("says capabilities are verified by the worker itself", async () => {
    // The product promise: a worker is only given work it proved it can
    // do. If that ever stops being true this line must change.
    mocks.apiRequest.mockResolvedValue([ONLINE_WORKER]);

    renderPage();

    expect(
      await screen.findByText(/verified by the worker itself/i),
    ).toBeInTheDocument();
  });
});

describe("Registration", () => {
  it("shows the enrollment token once, with its warning", async () => {
    // Stored only as a keyed digest, so this dialog is the single moment
    // it can ever be read. If it is not shown clearly the worker cannot
    // be enrolled at all.
    const token = "pacw-enroll-VERY-SECRET-VALUE";

    mocks.apiRequest.mockImplementation((path: string, options?: unknown) => {
      const method = (options as { method?: string })?.method;

      if (path === "/reports/workers" && method === "POST") {
        return Promise.resolve({
          worker: ONLINE_WORKER,
          enrollment_token: token,
          expires_at: "2026-08-13T11:00:00Z",
          instructions: "Run `pa-worker enroll ...` on the Windows machine.",
        });
      }

      return Promise.resolve([]);
    });

    const user = userEvent.setup();

    renderPage();

    await user.click(
      await screen.findByRole("button", { name: /register worker/i }),
    );

    const nameField = await screen.findByLabelText(/worker name/i);
    await user.type(nameField, "new-worker");

    await user.click(screen.getByRole("button", { name: /^register$/i }));

    expect(await screen.findByText(token)).toBeInTheDocument();
    expect(screen.getByText(/shown once/i)).toBeInTheDocument();
  });

  it("surfaces a duplicate-name refusal", async () => {
    mocks.apiRequest.mockImplementation((path: string, options?: unknown) => {
      const method = (options as { method?: string })?.method;

      if (path === "/reports/workers" && method === "POST") {
        return Promise.reject(
          new mocks.FakeApiError(
            409,
            "CONFLICT",
            "A worker named 'new-worker' already exists.",
          ),
        );
      }

      return Promise.resolve([]);
    });

    const user = userEvent.setup();

    renderPage();

    await user.click(
      await screen.findByRole("button", { name: /register worker/i }),
    );

    await user.type(await screen.findByLabelText(/worker name/i), "new-worker");
    await user.click(screen.getByRole("button", { name: /^register$/i }));

    await waitFor(() =>
      expect(mocks.toastError).toHaveBeenCalledWith(
        "A worker named 'new-worker' already exists.",
      ),
    );
  });
});

describe("Secret handling", () => {
  it("never renders a credential or secret field", async () => {
    // The API deliberately omits secret_hash and enrollment_token_hash.
    // This asserts the page cannot start displaying one.
    mocks.apiRequest.mockResolvedValue([
      {
        ...ONLINE_WORKER,
        // Simulate the API wrongly leaking these one day.
        secret_hash: "LEAKED-HASH-VALUE",
        enrollment_token_hash: "LEAKED-TOKEN-HASH",
      },
    ]);

    const { container } = renderPage();

    await screen.findByText("finance-reporting-01");

    expect(container.textContent).not.toContain("LEAKED-HASH-VALUE");
    expect(container.textContent).not.toContain("LEAKED-TOKEN-HASH");
  });
});
