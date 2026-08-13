/**
 * Execution history — the evidence trail for every report run.
 *
 * What matters here: a failure must be legible (status, code, retry
 * class), a retry must be visible as a *new* attempt rather than a
 * mutated one, and an artifact download must go through an authenticated
 * request rather than a bare link — an artifact id is an identifier, not
 * a capability.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
}));

vi.mock("@/lib/api-client", () => ({
  ApiError: class extends Error {},
  apiRequest: mocks.apiRequest,
  registerTokenAccessors: vi.fn(),
}));

import ExecutionsPage from "../page";

const SUCCEEDED = {
  id: "11111111-1111-1111-1111-111111111111",
  report_id: "rrrrrrrr-rrrr-rrrr-rrrr-rrrrrrrrrrrr",
  workbook_id: null,
  worker_id: null,
  status: "succeeded" as const,
  trigger_type: "manual",
  correlation_id: "cccccccc-cccc-cccc-cccc-cccccccccccc",
  attempt: 1,
  max_attempts: 3,
  parent_execution_id: null,
  queued_at: "2026-08-13T10:00:00Z",
  started_at: "2026-08-13T10:00:05Z",
  completed_at: "2026-08-13T10:00:42Z",
  duration_ms: 37000,
  timeout_seconds: 1200,
  error_code: null,
  error_message: null,
  retry_class: null,
  diagnostics: null,
  created_at: "2026-08-13T10:00:00Z",
};

const FAILED_RETRYABLE = {
  ...SUCCEEDED,
  id: "22222222-2222-2222-2222-222222222222",
  status: "failed" as const,
  duration_ms: 5000,
  error_code: "tm1_connection_failed",
  error_message: "The Planning Analytics server could not be reached.",
  retry_class: "retryable",
};

const RETRY_ATTEMPT = {
  ...SUCCEEDED,
  id: "33333333-3333-3333-3333-333333333333",
  status: "queued" as const,
  trigger_type: "retry",
  attempt: 2,
  parent_execution_id: FAILED_RETRYABLE.id,
  duration_ms: null,
  started_at: null,
  completed_at: null,
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <ExecutionsPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.apiRequest.mockReset();
  vi.unstubAllGlobals();
});

describe("Execution listing", () => {
  it("shows status, trigger and duration", async () => {
    mocks.apiRequest.mockResolvedValue([SUCCEEDED]);

    renderPage();

    expect(await screen.findByText("succeeded")).toBeInTheDocument();
    expect(screen.getByText("manual")).toBeInTheDocument();
    expect(screen.getByText("37s")).toBeInTheDocument();
  });

  it("makes a failure legible", async () => {
    mocks.apiRequest.mockResolvedValue([FAILED_RETRYABLE]);

    renderPage();

    expect(await screen.findByText("failed")).toBeInTheDocument();
    expect(
      screen.getByText(/Planning Analytics server could not be reached/i),
    ).toBeInTheDocument();
  });

  it("shows a retry as a new attempt, not a mutated one", async () => {
    // Executions are immutable; a retry is a separate row. If the UI
    // ever collapsed them the audit trail would look rewritten.
    mocks.apiRequest.mockResolvedValue([RETRY_ATTEMPT, FAILED_RETRYABLE]);

    renderPage();

    await screen.findByText("queued");

    expect(screen.getByText("2/3")).toBeInTheDocument();
    expect(screen.getByText("1/3")).toBeInTheDocument();
    expect(screen.getByText("retry")).toBeInTheDocument();
  });

  it("renders an em dash rather than a blank for an unfinished run", async () => {
    mocks.apiRequest.mockResolvedValue([RETRY_ATTEMPT]);

    renderPage();

    await screen.findByText("queued");

    // A blank cell reads as broken; "—" reads as not-yet.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("tells the user when there is no history", async () => {
    mocks.apiRequest.mockResolvedValue([]);

    renderPage();

    expect(await screen.findByText(/no executions yet/i)).toBeInTheDocument();
  });

  it("explains that retries preserve history", async () => {
    mocks.apiRequest.mockResolvedValue([SUCCEEDED]);

    renderPage();

    expect(
      await screen.findByText(/history of what actually happened stays intact/i),
    ).toBeInTheDocument();
  });
});

describe("Artifact download", () => {
  it("fetches with an Authorization header rather than a bare link", async () => {
    // The security property: an artifact id is an identifier, not a
    // capability. A plain <a href> would drop the credential and either
    // fail or, worse, imply the URL alone is sufficient.
    const detail = {
      ...SUCCEEDED,
      trace_log: null,
      artifacts: [
        {
          id: "aaaa1111-aaaa-1111-aaaa-111111111111",
          report_execution_id: SUCCEEDED.id,
          output_format: "xlsx",
          filename: "monthly-pl-11111111.xlsx",
          mime_type: "application/vnd.ms-excel",
          size_bytes: 20480,
          checksum: "abcdef1234567890",
          created_at: "2026-08-13T10:00:42Z",
        },
      ],
    };

    mocks.apiRequest.mockImplementation((path: string) =>
      Promise.resolve(path.includes(SUCCEEDED.id) ? detail : [SUCCEEDED]),
    );

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(new Blob(["data"])),
    });

    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("localStorage", {
      getItem: () => "test-access-token",
      setItem: () => {},
      removeItem: () => {},
    });
    // Only the two static helpers are stubbed. Replacing the whole URL
    // global breaks it as a constructor, which happy-dom needs when the
    // generated <a> is clicked — the test would still pass while the
    // download path silently threw.
    vi.stubGlobal(
      "URL",
      Object.assign(globalThis.URL, {
        createObjectURL: () => "blob:fake",
        revokeObjectURL: () => {},
      }),
    );

    const user = userEvent.setup();

    renderPage();

    await user.click(await screen.findByText("11111111"));
    await user.click(await screen.findByRole("button", { name: /download/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    const [url, options] = fetchMock.mock.calls[0];

    expect(url).toContain("/reports/artifacts/");
    expect(options.headers.Authorization).toBe("Bearer test-access-token");
  });
});
