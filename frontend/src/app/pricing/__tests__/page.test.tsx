/**
 * The pricing page's build-time fetch.
 *
 * This page is prerendered, so its fetch runs during `next build`. Next
 * gives a page 60 seconds, then kills the worker, retries twice, and
 * fails the whole deployment. `fetch` has no default timeout, so an API
 * that accepts the connection and then never answers takes the build
 * down with it — which is what a suspended service does, and what a
 * free-tier host does while waking from idle.
 *
 * The page already had a try/catch and a documented empty-catalog
 * fallback. It was defensive against the wrong failure: a *refused*
 * connection rejects and is caught, a *silent* one just hangs. These
 * tests pin the difference.
 */

import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PricingPage from "../page";

const originalFetch = globalThis.fetch;

function renderPage() {
  return PricingPage().then((element) => render(element));
}

beforeEach(() => {
  vi.useRealTimers();
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("Plan catalog fetch", () => {
  it("passes an abort signal so a hang cannot outlive the build", async () => {
    // The regression that matters. Without a signal this request waits
    // forever and the deployment dies at the 60s worker limit.
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ data: [] }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await renderPage();

    const [, init] = fetchMock.mock.calls[0];

    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it("gives up well inside the 60s static generation budget", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ data: [] }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const timeoutSpy = vi.spyOn(AbortSignal, "timeout");

    await renderPage();

    expect(timeoutSpy).toHaveBeenCalled();

    const [ms] = timeoutSpy.mock.calls[0];

    // Comfortably under 60s, with room for Next's retries. A value at or
    // above the budget would abort only after the worker was already
    // killed, which is no protection at all.
    expect(ms).toBeLessThan(30_000);
  });

  it("still renders when the request is aborted", async () => {
    // What a timeout actually looks like: a rejection, which the
    // existing catch turns into the empty-catalog fallback.
    globalThis.fetch = vi
      .fn()
      .mockRejectedValue(
        Object.assign(new Error("The operation was aborted"), {
          name: "TimeoutError",
        }),
      ) as unknown as typeof fetch;

    await renderPage();

    // The shell survives — a pricing page that errors is worse than one
    // that asks you to get in touch.
    expect(
      screen.getByRole("heading", { name: /plans/i, level: 1 }),
    ).toBeInTheDocument();
  });

  it("still renders when the API refuses the connection", async () => {
    globalThis.fetch = vi
      .fn()
      .mockRejectedValue(new Error("ECONNREFUSED")) as unknown as typeof fetch;

    await renderPage();

    expect(
      screen.getByRole("heading", { name: /plans/i, level: 1 }),
    ).toBeInTheDocument();
  });

  it("still renders when the API answers with an error status", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({}),
    }) as unknown as typeof fetch;

    await renderPage();

    expect(
      screen.getByRole("heading", { name: /plans/i, level: 1 }),
    ).toBeInTheDocument();
  });

  it("renders the plans the API returns", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        data: [
          {
            key: "professional",
            name: "Professional",
            description: "For teams",
            monthly_token_limit: 5_000_000,
            max_users: 25,
            max_connections: 5,
            features: ["Everything in Starter"],
            price_label: "$99/month",
          },
        ],
      }),
    }) as unknown as typeof fetch;

    await renderPage();

    expect(screen.getByText("Professional")).toBeInTheDocument();
    expect(screen.getByText("$99/month")).toBeInTheDocument();
  });
});
