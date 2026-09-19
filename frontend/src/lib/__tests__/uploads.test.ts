/**
 * Files go to storage directly, or fall back honestly.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

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

  return { FakeApiError, apiRequest: vi.fn() };
});

vi.mock("@/lib/api-client", () => ({
  ApiError: mocks.FakeApiError,
  apiRequest: mocks.apiRequest,
}));

import { directUpload, directUploadAll } from "../uploads";

const file = new File(["x".repeat(10)], "plan.xlsx", { type: "application/x" });

afterEach(() => {
  vi.unstubAllGlobals();
  mocks.apiRequest.mockReset();
});

describe("directUpload", () => {
  it("returns null where the server has no direct upload, so callers fall back", async () => {
    mocks.apiRequest.mockRejectedValue(
      new mocks.FakeApiError(503, "DIRECT_UPLOAD_UNAVAILABLE", "No S3."),
    );

    expect(await directUpload(file)).toBeNull();
  });

  it("PUTs the bytes to the signed URL with its headers and no token", async () => {
    mocks.apiRequest.mockResolvedValue({
      key: "org/o/uploads/u/plan.xlsx",
      url: "https://s3.test/put",
      headers: { "Content-Type": "application/x", "x-amz-server-side-encryption": "AES256" },
      expires_in: 900,
    });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    vi.stubGlobal("fetch", fetchMock);

    const ref = await directUpload(file);

    expect(ref).toEqual({ key: "org/o/uploads/u/plan.xlsx", filename: "plan.xlsx" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://s3.test/put");
    expect(init.method).toBe("PUT");
    expect(init.headers["x-amz-server-side-encryption"]).toBe("AES256");
    expect(init.headers.Authorization).toBeUndefined();
    expect(init.body).toBe(file);
  });

  it("reports a storage refusal rather than pretending the upload happened", async () => {
    mocks.apiRequest.mockResolvedValue({
      key: "k",
      url: "https://s3.test/put",
      headers: {},
      expires_in: 900,
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 403 }));

    await expect(directUpload(file)).rejects.toMatchObject({ status: 403, code: "UPLOAD_FAILED" });
  });

  it("falls back when the PUT never reaches storage, as with a missing CORS rule", async () => {
    mocks.apiRequest.mockResolvedValue({
      key: "k",
      url: "https://s3.test/put",
      headers: {},
      expires_in: 900,
    });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    expect(await directUpload(file)).toBeNull();
  });

  it("re-raises anything other than 'not configured'", async () => {
    mocks.apiRequest.mockRejectedValue(
      new mocks.FakeApiError(422, "VALIDATION_ERROR", "Too large."),
    );

    await expect(directUpload(file)).rejects.toMatchObject({ status: 422 });
  });
});

describe("directUploadAll", () => {
  it("is all or nothing", async () => {
    mocks.apiRequest.mockRejectedValue(
      new mocks.FakeApiError(503, "DIRECT_UPLOAD_UNAVAILABLE", "No S3."),
    );

    expect(await directUploadAll([file, file])).toBeNull();
  });
});
