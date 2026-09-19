/**
 * Coding Standards — the upload that sent an empty body.
 *
 * QA finding: both "Preview report" and "Set as our standards" posted a
 * multipart body with no parts and got a 422, with no error shown. The
 * cause was a `FileList` handed to an async mutation and then emptied by
 * the input reset on the very next line — a FileList is a live view of
 * the input, not a copy. The handlers now snapshot to an array first.
 *
 * These tests pin the invariant that matters: what reaches the API is a
 * FormData that actually contains the chosen file, even though the input
 * has been cleared by the time the request is built.
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
    toastError: vi.fn(),
    toastWarning: vi.fn(),
  };
});

vi.mock("@/lib/api-client", () => ({
  ApiError: mocks.FakeApiError,
  apiRequest: mocks.apiRequest,
  uploadRequest: mocks.uploadRequest,
  registerTokenAccessors: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    success: mocks.toastSuccess,
    error: mocks.toastError,
    warning: mocks.toastWarning,
  },
}));

import StandardsPage from "../page";

const RUN = {
  replaced_existing: true,
  conventions_learned: 2,
  processes_parsed: 9,
  processes_failed: 0,
  note: null,
  files_with_stored_credentials: 0,
  patterns: [],
};

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

/** The two hidden inputs, in DOM order: learn first, preview second. */
function fileInputs(container: HTMLElement) {
  return Array.from(
    container.querySelectorAll<HTMLInputElement>('input[type="file"]'),
  );
}

beforeEach(() => {
  mocks.apiRequest.mockReset();
  mocks.uploadRequest.mockReset();
  mocks.toastSuccess.mockReset();
  mocks.toastError.mockReset();
  mocks.toastWarning.mockReset();
  // A server with no S3: /uploads answers 503 and the pages fall back to
  // multipart, which is what every test below exercises. The direct
  // path has its own test at the end.
  mocks.apiRequest.mockImplementation((path: string) =>
    path === "/uploads"
      ? Promise.reject(
          new mocks.FakeApiError(503, "DIRECT_UPLOAD_UNAVAILABLE", "No S3."),
        )
      : Promise.resolve({ conventions: [] }),
  );
});

describe("Set as our standards", () => {
  it("sends the chosen file even though the input is reset afterwards", async () => {
    mocks.uploadRequest.mockResolvedValue(RUN);

    const user = userEvent.setup();
    const { container } = renderPage();
    const [learnInput] = fileInputs(container);
    const file = new File(["#Section=Prolog\n"], "Load.pro", { type: "text/plain" });

    await user.upload(learnInput, file);

    await waitFor(() => expect(mocks.uploadRequest).toHaveBeenCalledTimes(1));

    const [path, form] = mocks.uploadRequest.mock.calls[0] as [string, FormData];

    expect(path).toBe("/learning/corpus");
    // The regression: with a live FileList this was an empty FormData.
    const sent = form.getAll("files") as File[];
    expect(sent).toHaveLength(1);
    expect(sent[0].name).toBe("Load.pro");
    // And the input really was cleared, so the same file can be chosen twice.
    expect(learnInput.value).toBe("");
  });

  it("reports what was learned", async () => {
    mocks.uploadRequest.mockResolvedValue(RUN);

    const user = userEvent.setup();
    const { container } = renderPage();
    const [learnInput] = fileInputs(container);

    await user.upload(learnInput, new File(["x"], "Load.pro"));

    await waitFor(() =>
      expect(mocks.toastSuccess).toHaveBeenCalledWith(
        "Learned 2 standard(s) from 9 processes.",
      ),
    );
  });

  it("shows the server's error instead of failing silently", async () => {
    // The other half of the finding: a 422 produced no toast at all.
    mocks.uploadRequest.mockRejectedValue(
      new mocks.FakeApiError(422, "VALIDATION_ERROR", "files: Field required"),
    );

    const user = userEvent.setup();
    const { container } = renderPage();
    const [learnInput] = fileInputs(container);

    await user.upload(learnInput, new File(["x"], "Load.pro"));

    await waitFor(() =>
      expect(mocks.toastError).toHaveBeenCalledWith("files: Field required"),
    );
  });
});

describe("Preview report", () => {
  it("sends the file to the report endpoint and shows the result", async () => {
    mocks.uploadRequest.mockResolvedValue({ markdown: "# Report\n\n9 processes read." });

    const user = userEvent.setup();
    const { container } = renderPage();
    const [, previewInput] = fileInputs(container);

    await user.upload(previewInput, new File(["x"], "Load.pro"));

    await waitFor(() => expect(mocks.uploadRequest).toHaveBeenCalledTimes(1));

    const [path, form] = mocks.uploadRequest.mock.calls[0] as [string, FormData];

    expect(path).toBe("/learning/report");
    expect(form.getAll("files")).toHaveLength(1);
    expect(await screen.findByText(/9 processes read/)).toBeInTheDocument();
  });

  it("sends every selected file when several are chosen", async () => {
    mocks.uploadRequest.mockResolvedValue({ markdown: "ok" });

    const user = userEvent.setup();
    const { container } = renderPage();
    const [, previewInput] = fileInputs(container);

    await user.upload(previewInput, [
      new File(["a"], "One.pro"),
      new File(["b"], "Two.pro"),
    ]);

    await waitFor(() => expect(mocks.uploadRequest).toHaveBeenCalledTimes(1));

    const [, form] = mocks.uploadRequest.mock.calls[0] as [string, FormData];

    expect((form.getAll("files") as File[]).map((f) => f.name)).toEqual([
      "One.pro",
      "Two.pro",
    ]);
  });
});

describe("where the server offers direct upload", () => {
  it("puts the file in storage and records it by key", async () => {
    // What Vercel needs: the file never crosses the API. The page asks
    // for a signed URL, PUTs the bytes there, and posts only the key.
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    vi.stubGlobal("fetch", fetchMock);

    mocks.apiRequest.mockImplementation((path: string) => {
      if (path === "/uploads") {
        return Promise.resolve({
          key: "org/o1/uploads/u1/Load.pro",
          url: "https://s3.test/put",
          headers: { "Content-Type": "text/plain" },
          expires_in: 900,
        });
      }
      if (path === "/learning/corpus/from-upload") return Promise.resolve(RUN);
      return Promise.resolve({ conventions: [] });
    });

    const user = userEvent.setup();
    const { container } = renderPage();
    const [learnInput] = fileInputs(container);

    await user.upload(
      learnInput,
      new File(["#Section=Prolog\n"], "Load.pro", { type: "text/plain" }),
    );

    await waitFor(() =>
      expect(mocks.apiRequest).toHaveBeenCalledWith(
        "/learning/corpus/from-upload",
        expect.objectContaining({
          method: "POST",
          body: { uploads: [{ key: "org/o1/uploads/u1/Load.pro", filename: "Load.pro" }] },
        }),
      ),
    );

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://s3.test/put");
    expect(init.method).toBe("PUT");
    // The session token must never go to storage.
    expect(init.headers.Authorization).toBeUndefined();
    expect(mocks.uploadRequest).not.toHaveBeenCalled();

    vi.unstubAllGlobals();
  });
});
