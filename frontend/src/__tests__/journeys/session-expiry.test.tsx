/**
 * Journey: an access token expires mid-session, is refreshed, and the user
 * carries on without noticing.
 *
 * Deliberately NOT a unit test. The real api-client, the real AuthProvider
 * and the real protected layout run together — only `fetch` is stubbed,
 * because the network is the only thing that genuinely cannot run here.
 * Each of these pieces is already covered in isolation; the failures worth
 * catching live in the seams between them.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => "/dashboard",
}));

vi.mock("@/components/app-sidebar", () => ({
  AppSidebar: () => <nav data-testid="sidebar" />,
}));
vi.mock("@/components/app-header", () => ({
  AppHeader: () => <header data-testid="header" />,
}));

import { apiRequest } from "@/lib/api-client";
import { AuthProvider, useAuth } from "@/lib/auth-context";
import AppLayout from "@/app/(app)/layout";

const STORAGE_KEY = "pa-copilot-tokens";

const ME = {
  id: "u1",
  username: "harish",
  email: "harish@example.com",
  first_name: "Harish",
  last_name: "Kollati",
  is_active: true,
  organization_id: "o1",
  registration_status: "approved",
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const ok = (data: unknown) => json({ success: true, data });
const unauthorized = () =>
  json({ success: false, error: { code: "AUTH", message: "expired" } }, 401);

/** Renders a page that fetches, inside the real provider and layout. */
function Dashboard() {
  const { user } = useAuth();
  return <div>Signed in as {user?.first_name}</div>;
}

function renderApp() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <AppLayout>
          <Dashboard />
        </AppLayout>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

function storedTokens() {
  const raw = window.localStorage.getItem(STORAGE_KEY);
  return raw ? JSON.parse(raw) : null;
}

beforeEach(() => {
  window.localStorage.clear();
  replace.mockClear();
});

describe("an expired access token", () => {
  it("is refreshed transparently and the user stays signed in", async () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ accessToken: "stale", refreshToken: "refresh-1" }),
    );

    const fetchMock = vi
      .fn()
      // Bootstrap /auth/me with the stale access token.
      .mockResolvedValueOnce(unauthorized())
      // The client refreshes...
      .mockResolvedValueOnce(
        ok({ access_token: "fresh", refresh_token: "refresh-2" }),
      )
      // ...and replays /auth/me.
      .mockResolvedValueOnce(ok(ME));

    vi.stubGlobal("fetch", fetchMock);

    renderApp();

    // The user never sees a login screen.
    expect(await screen.findByText(/Signed in as Harish/)).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it("persists the rotated refresh token, not the spent one", async () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ accessToken: "stale", refreshToken: "refresh-1" }),
    );

    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(unauthorized())
        .mockResolvedValueOnce(
          ok({ access_token: "fresh", refresh_token: "refresh-2" }),
        )
        .mockResolvedValueOnce(ok(ME)),
    );

    renderApp();
    await screen.findByText(/Signed in as Harish/);

    // The backend rotates refresh tokens and revokes the spent one, so
    // keeping the old value would break the *next* refresh entirely.
    await waitFor(() =>
      expect(storedTokens()).toEqual({
        accessToken: "fresh",
        refreshToken: "refresh-2",
      }),
    );
  });

  it("continues to work for requests made after the refresh", async () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ accessToken: "stale", refreshToken: "refresh-1" }),
    );

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(unauthorized())
      .mockResolvedValueOnce(
        ok({ access_token: "fresh", refresh_token: "refresh-2" }),
      )
      .mockResolvedValueOnce(ok(ME))
      .mockResolvedValueOnce(ok({ cubes: 4 }));

    vi.stubGlobal("fetch", fetchMock);

    renderApp();
    await screen.findByText(/Signed in as Harish/);

    await expect(apiRequest("/tm1/summary")).resolves.toEqual({ cubes: 4 });

    // The follow-up request carries the NEW token — the accessor wiring
    // between the provider and the client is what this proves.
    const lastCall = fetchMock.mock.calls.at(-1)!;
    expect(lastCall[1].headers.Authorization).toBe("Bearer fresh");
  });
});

describe("a refresh token that is itself rejected", () => {
  it("clears the session and sends the user to login", async () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ accessToken: "stale", refreshToken: "revoked" }),
    );

    vi.stubGlobal("location", { href: "" });
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(unauthorized())
        // Refresh rejected — reuse detection, logout-all, or expiry.
        .mockResolvedValueOnce(unauthorized()),
    );

    renderApp();

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));

    // Stale credentials must not survive; the next reload would otherwise
    // repeat the whole failing dance.
    expect(storedTokens()).toBeNull();
    expect(screen.queryByTestId("sidebar")).not.toBeInTheDocument();
  });
});

describe("no stored session at all", () => {
  it("goes straight to login without calling the API", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    renderApp();

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));

    expect(fetchMock).not.toHaveBeenCalled();
  });
});
