/**
 * The API client is the single choke point every request passes through:
 * auth headers, token refresh, timeouts, and error shaping all live here.
 * A regression is invisible in one page and breaks all of them.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiRequest, registerTokenAccessors } from "@/lib/api-client";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const ok = (data: unknown) => jsonResponse({ success: true, data });
const fail = (code: string, message: string, status = 400) =>
  jsonResponse({ success: false, error: { code, message } }, status);

/** Await a call expected to reject, returning the ApiError it threw. */
async function rejectsWith(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    return error as ApiError;
  }

  throw new Error("expected the request to reject, but it resolved");
}

let accessToken: string | null;
let refreshToken: string | null;
let setTokens: ReturnType<typeof vi.fn<
  (tokens: { accessToken: string; refreshToken: string } | null) => void
>>;

beforeEach(() => {
  accessToken = "access-1";
  refreshToken = "refresh-1";
  setTokens = vi.fn();

  registerTokenAccessors({
    getAccessToken: () => accessToken,
    getRefreshToken: () => refreshToken,
    setTokens,
  });
});

describe("request shaping", () => {
  it("unwraps the success envelope", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok({ id: 7 })));

    await expect(apiRequest("/thing")).resolves.toEqual({ id: 7 });
  });

  it("attaches the bearer token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok(null));
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest("/thing");

    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe(
      "Bearer access-1",
    );
  });

  it("omits the bearer token when skipAuth is set", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok(null));
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest("/auth/login", { skipAuth: true, method: "POST" });

    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBeUndefined();
  });

  it("raises ApiError carrying the server's code and message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(fail("RATE_LIMITED", "Slow down.", 429)),
    );

    await expect(apiRequest("/thing")).rejects.toMatchObject({
      code: "RATE_LIMITED",
      message: "Slow down.",
      status: 429,
    });
  });
});

describe("failures that are not JSON", () => {
  it("turns an unreadable body into an ApiError, not a SyntaxError", async () => {
    // A proxy 502 returns HTML. Throwing SyntaxError here reads as a
    // frontend bug rather than an upstream outage.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("<html>502 Bad Gateway</html>", { status: 502 }),
      ),
    );

    const error = await rejectsWith(apiRequest("/thing"));

    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe("INVALID_RESPONSE");
    expect(error.status).toBe(502);
  });

  it("reports a timeout as TIMEOUT with a readable message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(
        new DOMException("The operation timed out.", "TimeoutError"),
      ),
    );

    const error = await rejectsWith(apiRequest("/thing"));

    expect(error.code).toBe("TIMEOUT");
    expect(error.message).toMatch(/did not respond/i);
  });

  it("reports an unreachable server as NETWORK_ERROR", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("failed")));

    const error = await rejectsWith(apiRequest("/thing"));

    expect(error.code).toBe("NETWORK_ERROR");
  });
});

describe("token refresh", () => {
  it("refreshes once on 401 and replays the request", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(fail("AUTH", "expired", 401))
      .mockResolvedValueOnce(
        ok({ access_token: "access-2", refresh_token: "refresh-2" }),
      )
      .mockResolvedValueOnce(ok({ id: 7 }));

    vi.stubGlobal("fetch", fetchMock);

    await expect(apiRequest("/thing")).resolves.toEqual({ id: 7 });

    expect(setTokens).toHaveBeenCalledWith({
      accessToken: "access-2",
      refreshToken: "refresh-2",
    });
  });

  it("clears tokens when the refresh itself fails", async () => {
    vi.stubGlobal("location", { href: "" });

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(fail("AUTH", "expired", 401))
      .mockResolvedValueOnce(fail("AUTH", "no", 401));

    vi.stubGlobal("fetch", fetchMock);

    await expect(apiRequest("/thing")).rejects.toMatchObject({ status: 401 });

    expect(setTokens).toHaveBeenCalledWith(null);
  });

  it("does not attempt a refresh when there is no refresh token", async () => {
    refreshToken = null;
    vi.stubGlobal("location", { href: "" });

    const fetchMock = vi.fn().mockResolvedValue(fail("AUTH", "expired", 401));
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiRequest("/thing")).rejects.toMatchObject({ status: 401 });

    // One attempt only — no refresh call, no replay.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not refresh on a 401 from an unauthenticated call", async () => {
    const fetchMock = vi.fn().mockResolvedValue(fail("AUTH", "bad creds", 401));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      apiRequest("/auth/login", { skipAuth: true, method: "POST" }),
    ).rejects.toMatchObject({ status: 401 });

    // Refreshing after a failed login would be nonsense.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
