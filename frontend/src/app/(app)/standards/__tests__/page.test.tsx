/**
 * Coding Standards — the surface where a team's TM1 house style is set.
 *
 * Tested from the user's side. The two things that matter most here are not
 * the happy path: that a corpus which produced nothing tells the user their
 * existing standards were kept rather than silently reporting success, and
 * that uploading exports containing datasource credentials warns them.
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
    uploadRequest: vi.fn(),
    toastSuccess: vi.fn(),
    toastWarning: vi.fn(),
    toastError: vi.fn(),
  };
});

vi.mock("@/lib/api-client", () => ({
  ApiError: mocks.FakeApiError,
  apiRequest: mocks.apiRequest,
  uploadRequest: mocks.uploadRequest,
  streamRequest: vi.fn(),
  registerTokenAccessors: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    success: mocks.toastSuccess,
    warning: mocks.toastWarning,
    error: mocks.toastError,
  },
}));

import StandardsPage from "../page";

const CONVENTION = {
  key: "no_inline_comments",
  statement: "Comments sit on their own line above the code they describe.",
  confidence: 0.93,
  support: 64,
  sample: 64,
  examples: ["DATA - Load - FX Rates"],
  counter_examples: [],
};

function emptyRun(overrides: Record<string, unknown> = {}) {
  return {
    processes_parsed: 3,
    processes_failed: 0,
    conventions_learned: 4,
    patterns: [],
    rejected: [],
    replaced_existing: true,
    note: null,
    files_with_stored_credentials: 0,
    ...overrides,
  };
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <StandardsPage />
    </QueryClientProvider>,
  );
}

async function upload(buttonName: RegExp) {
  const file = new File(["601,100"], "tm1.zip", { type: "application/zip" });
  const user = userEvent.setup();

  await user.click(screen.getByRole("button", { name: buttonName }));

  // The buttons proxy to hidden file inputs; drive the input directly.
  const inputs = document.querySelectorAll<HTMLInputElement>('input[type="file"]');
  const target = buttonName.source.includes("Preview") ? inputs[1] : inputs[0];

  await user.upload(target, file);
}

describe("Coding Standards", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.apiRequest.mockResolvedValue({ process_count: 0, conventions: [] });
  });

  it("shows learned standards with the evidence behind each", async () => {
    mocks.apiRequest.mockResolvedValue({
      process_count: 64,
      conventions: [CONVENTION],
    });

    renderPage();

    expect(await screen.findByText(CONVENTION.statement)).toBeInTheDocument();
    expect(
      screen.getByText(/Followed by 64 of 64 processes/),
    ).toBeInTheDocument();
  });

  it("tells a new organization nothing is learned rather than showing an empty list", async () => {
    renderPage();

    expect(await screen.findByText(/Nothing learned yet/)).toBeInTheDocument();
    expect(screen.getByText(/documented IBM practice/)).toBeInTheDocument();
  });

  it("warns instead of celebrating when existing standards were kept", async () => {
    mocks.uploadRequest.mockResolvedValue(
      emptyRun({
        replaced_existing: false,
        note: "This corpus of 3 process(es) produced no convention confident enough to become a standard, so the 4 already learned were kept.",
      }),
    );

    renderPage();
    await upload(/Set as our standards/);

    await waitFor(() => {
      expect(mocks.toastWarning).toHaveBeenCalled();
    });

    expect(mocks.toastSuccess).not.toHaveBeenCalled();
    expect(await screen.findByText(/already learned were kept/)).toBeInTheDocument();
  });

  it("warns that uploaded exports carry datasource credentials", async () => {
    mocks.uploadRequest.mockResolvedValue(
      emptyRun({ processes_parsed: 64, files_with_stored_credentials: 59 }),
    );

    renderPage();
    await upload(/Set as our standards/);

    expect(
      await screen.findByText(/saved datasource username or password/),
    ).toBeInTheDocument();
  });

  it("previews a report without it becoming the standard", async () => {
    mocks.uploadRequest.mockResolvedValue({
      markdown: "# Company TM1 Standards Report\n\nMeasured from 64 processes.",
    });

    renderPage();
    await upload(/Preview report/);

    expect(await screen.findByText(/Nothing was saved/)).toBeInTheDocument();
    expect(mocks.toastSuccess).not.toHaveBeenCalled();
  });

  it("surfaces an upload failure to the user", async () => {
    mocks.uploadRequest.mockRejectedValue(
      new mocks.FakeApiError(422, "VALIDATION_ERROR", "No TurboIntegrator exports found."),
    );

    renderPage();
    await upload(/Set as our standards/);

    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith(
        "No TurboIntegrator exports found.",
      );
    });
  });
});
