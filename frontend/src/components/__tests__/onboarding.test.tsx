/**
 * First-login onboarding.
 *
 * The decisions worth pinning are about *persistence*, not appearance:
 * who is offered the tour, what each button writes, and — most
 * importantly — that finishing it once means never being shown it
 * again. An onboarding modal that reappears is worse than none.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  refreshUser: vi.fn(),
  push: vi.fn(),
  user: {
    id: "u-1",
    username: "admin",
    email: "admin@example.com",
    first_name: "Admin",
    last_name: "User",
    is_active: true,
    organization_id: "org-1",
    onboarding_completed_at: null as string | null,
    onboarding_dismissed_at: null as string | null,
  },
}));

vi.mock("@/lib/api-client", () => ({
  apiRequest: mocks.apiRequest,
  ApiError: class extends Error {},
  registerTokenAccessors: vi.fn(),
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ user: mocks.user, refreshUser: mocks.refreshUser }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push, replace: vi.fn() }),
  usePathname: () => "/dashboard",
  useSearchParams: () => new URLSearchParams(),
}));

import { Onboarding } from "../onboarding";

function renderOnboarding() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <Onboarding />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.apiRequest.mockResolvedValue({});
  mocks.user.onboarding_completed_at = null;
  mocks.user.onboarding_dismissed_at = null;
  document.body.innerHTML = "";
});

describe("who sees it", () => {
  it("welcomes a user who has never seen it", async () => {
    renderOnboarding();

    expect(
      await screen.findByRole("heading", { name: /welcome to pa-copilot/i }),
    ).toBeInTheDocument();
  });

  it("does not nag a user who finished it", () => {
    // The whole point of persisting server-side.
    mocks.user.onboarding_completed_at = "2026-09-16T00:00:00Z";

    renderOnboarding();

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("does not nag a user who dismissed it", () => {
    mocks.user.onboarding_dismissed_at = "2026-09-16T00:00:00Z";

    renderOnboarding();

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("the three choices", () => {
  it("records a skip so it does not return on the next page load", async () => {
    const user = userEvent.setup();

    renderOnboarding();

    await user.click(await screen.findByRole("button", { name: /skip tour/i }));

    await waitFor(() =>
      expect(mocks.apiRequest).toHaveBeenCalledWith(
        "/users/me/onboarding",
        expect.objectContaining({
          method: "POST",
          body: { action: "dismissed" },
        }),
      ),
    );
  });

  it("writes nothing for 'remind me later'", async () => {
    // "Later" means this session. Persisting it would quietly opt
    // someone out via a button they pressed to get on with something.
    const user = userEvent.setup();

    renderOnboarding();

    await user.click(
      await screen.findByRole("button", { name: /remind me later/i }),
    );

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );

    expect(mocks.apiRequest).not.toHaveBeenCalled();
  });

  it("starts the tour without recording anything yet", async () => {
    // Starting is not finishing — a user who closes the tab midway
    // should be offered it again.
    const user = userEvent.setup();

    renderOnboarding();

    await user.click(await screen.findByRole("button", { name: /start tour/i }));

    expect(
      await screen.findByRole("dialog", { name: /your workspace/i }),
    ).toBeInTheDocument();
    expect(mocks.apiRequest).not.toHaveBeenCalled();
  });
});

describe("running the tour", () => {
  async function startTour(user: ReturnType<typeof userEvent.setup>) {
    renderOnboarding();
    await user.click(await screen.findByRole("button", { name: /start tour/i }));
  }

  it("shows progress so the user knows how long it is", async () => {
    const user = userEvent.setup();

    await startTour(user);

    expect(await screen.findByText(/step 1 of/i)).toBeInTheDocument();
  });

  it("advances and goes back", async () => {
    const user = userEvent.setup();

    await startTour(user);

    await user.click(screen.getByRole("button", { name: /next/i }));
    expect(await screen.findByText(/step 2 of/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /back/i }));
    expect(await screen.findByText(/step 1 of/i)).toBeInTheDocument();
  });

  it("offers no Back on the first step", async () => {
    const user = userEvent.setup();

    await startTour(user);

    expect(
      screen.queryByRole("button", { name: /back/i }),
    ).not.toBeInTheDocument();
  });

  it("records completion when finished", async () => {
    const user = userEvent.setup();

    await startTour(user);

    // Walk to the end.
    for (let step = 0; step < 20; step += 1) {
      const next = screen.queryByRole("button", { name: /^next$/i });
      if (!next) break;
      await user.click(next);
    }

    await user.click(await screen.findByRole("button", { name: /finish/i }));

    await waitFor(() =>
      expect(mocks.apiRequest).toHaveBeenCalledWith(
        "/users/me/onboarding",
        expect.objectContaining({ body: { action: "completed" } }),
      ),
    );
  });

  it("records a dismissal when skipped mid-tour", async () => {
    const user = userEvent.setup();

    await startTour(user);
    await user.click(screen.getByRole("button", { name: /next/i }));
    await user.click(screen.getByRole("button", { name: /skip tour/i }));

    await waitFor(() =>
      expect(mocks.apiRequest).toHaveBeenCalledWith(
        "/users/me/onboarding",
        expect.objectContaining({ body: { action: "dismissed" } }),
      ),
    );
  });

  it("navigates to the screen a step belongs to", async () => {
    // Steps span routes; the tour has to take the user with it.
    const user = userEvent.setup();

    await startTour(user);

    // Step 4 lives on /chat (the voice control).
    for (let step = 0; step < 3; step += 1) {
      await user.click(screen.getByRole("button", { name: /^next$/i }));
    }

    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/chat"));
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();

    await startTour(user);
    await user.keyboard("{Escape}");

    await waitFor(() =>
      expect(
        screen.queryByText(/step 1 of/i),
      ).not.toBeInTheDocument(),
    );
  });
});
