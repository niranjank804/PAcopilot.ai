const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  code: string;
  status: number;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

interface ApiSuccess<T> {
  success: true;
  data: T;
}

interface ApiFailure {
  success: false;
  error: { code: string; message: string };
}

type ApiEnvelope<T> = ApiSuccess<T> | ApiFailure;

type TokenGetter = () => string | null;
type TokenSetter = (
  tokens: { accessToken: string; refreshToken: string } | null,
) => void;

let getAccessToken: TokenGetter = () => null;
let getRefreshToken: TokenGetter = () => null;
let setTokens: TokenSetter = () => {};

/** Wired up once by AuthProvider so this module-level client can read/write
 * tokens without importing React state directly. */
export function registerTokenAccessors(accessors: {
  getAccessToken: TokenGetter;
  getRefreshToken: TokenGetter;
  setTokens: TokenSetter;
}) {
  getAccessToken = accessors.getAccessToken;
  getRefreshToken = accessors.getRefreshToken;
  setTokens = accessors.setTokens;
}

let refreshPromise: Promise<boolean> | null = null;

/** Exactly one refresh attempt per 401, shared across concurrent callers via
 * refreshPromise so a burst of parallel requests doesn't trigger a burst of
 * refresh calls — no retry loop beyond this single attempt. */
async function refreshAccessToken(): Promise<boolean> {
  const refreshToken = getRefreshToken();

  if (!refreshToken) {
    return false;
  }

  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        const res = await fetch(`${API_URL}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });

        if (!res.ok) {
          return false;
        }

        const body = (await res.json()) as ApiEnvelope<{
          access_token: string;
          refresh_token: string;
        }>;

        if (!body.success) {
          return false;
        }

        setTokens({
          accessToken: body.data.access_token,
          refreshToken: body.data.refresh_token,
        });

        return true;
      } catch {
        return false;
      } finally {
        refreshPromise = null;
      }
    })();
  }

  return refreshPromise;
}

/** Generous enough for an agent tool loop, finite so a stalled request
 * surfaces as an error the UI can show instead of spinning forever. */
const DEFAULT_TIMEOUT_MS = 120_000;

interface RequestOptions {
  method?: string;
  body?: unknown;
  /** Skip attaching the access token — used for /auth/login itself. */
  skipAuth?: boolean;
  timeoutMs?: number;
}

export async function apiRequest<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const {
    method = "GET",
    body,
    skipAuth = false,
    timeoutMs = DEFAULT_TIMEOUT_MS,
  } = options;

  const doFetch = async (): Promise<Response> => {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };

    if (!skipAuth) {
      const token = getAccessToken();

      if (token) {
        headers.Authorization = `Bearer ${token}`;
      }
    }

    try {
      return await fetch(`${API_URL}${path}`, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: AbortSignal.timeout(timeoutMs),
      });
    } catch (error) {
      // Both a timeout and a dropped connection arrive here as a thrown
      // DOMException; either way the caller needs an ApiError it can
      // render, not an opaque rejection.
      if (error instanceof DOMException && error.name === "TimeoutError") {
        throw new ApiError(
          408,
          "TIMEOUT",
          `The server did not respond within ${Math.round(timeoutMs / 1000)}s.`,
        );
      }

      throw new ApiError(
        0,
        "NETWORK_ERROR",
        "Could not reach the server. Check your connection and try again.",
      );
    }
  };

  let response = await doFetch();

  if (response.status === 401 && !skipAuth) {
    const refreshed = await refreshAccessToken();

    if (refreshed) {
      response = await doFetch();
    } else {
      setTokens(null);

      if (typeof window !== "undefined") {
        window.location.href = "/login";
      }

      throw new ApiError(401, "AUTHENTICATION_ERROR", "Session expired");
    }
  }

  return unwrap<T>(response);
}

/** A non-JSON body means something between the browser and the API answered
 * (proxy 502, gateway timeout page). Surfacing the status beats throwing a
 * bare SyntaxError that reads as a frontend bug. */
async function unwrap<T>(response: Response): Promise<T> {
  let payload: ApiEnvelope<T>;

  try {
    payload = (await response.json()) as ApiEnvelope<T>;
  } catch {
    throw new ApiError(
      response.status,
      "INVALID_RESPONSE",
      `The server returned an unreadable response (HTTP ${response.status}).`,
    );
  }

  if (!payload.success) {
    throw new ApiError(response.status, payload.error.code, payload.error.message);
  }

  return payload.data;
}

/** Same auth/refresh handling as apiRequest, but for multipart file uploads
 * — no Content-Type header is set so the browser fills in the multipart
 * boundary itself, and the body is passed through as FormData rather than
 * JSON-encoded. */
export async function uploadRequest<T>(
  path: string,
  formData: FormData,
): Promise<T> {
  const doFetch = async (): Promise<Response> => {
    const headers: Record<string, string> = {};
    const token = getAccessToken();

    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }

    return fetch(`${API_URL}${path}`, {
      method: "POST",
      headers,
      body: formData,
    });
  };

  let response = await doFetch();

  if (response.status === 401) {
    const refreshed = await refreshAccessToken();

    if (refreshed) {
      response = await doFetch();
    } else {
      setTokens(null);

      if (typeof window !== "undefined") {
        window.location.href = "/login";
      }

      throw new ApiError(401, "AUTHENTICATION_ERROR", "Session expired");
    }
  }

  return unwrap<T>(response);
}

/** Same auth/refresh handling as apiRequest, but for POST endpoints that
 * respond with a Server-Sent Events stream instead of a JSON envelope. */
export async function* streamRequest<T>(
  path: string,
  body: unknown,
): AsyncGenerator<T> {
  const doFetch = async (): Promise<Response> => {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    const token = getAccessToken();

    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }

    return fetch(`${API_URL}${path}`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
  };

  let response = await doFetch();

  if (response.status === 401) {
    const refreshed = await refreshAccessToken();

    if (refreshed) {
      response = await doFetch();
    } else {
      setTokens(null);

      if (typeof window !== "undefined") {
        window.location.href = "/login";
      }

      throw new ApiError(401, "AUTHENTICATION_ERROR", "Session expired");
    }
  }

  if (!response.ok || !response.body) {
    throw new ApiError(response.status, "STREAM_ERROR", "The stream request failed.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();

    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });

    let boundary = buffer.indexOf("\n\n");

    while (boundary !== -1) {
      const rawEvent = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);

      for (const line of rawEvent.split("\n")) {
        if (line.startsWith("data: ")) {
          yield JSON.parse(line.slice(6)) as T;
        }
      }

      boundary = buffer.indexOf("\n\n");
    }
  }
}
