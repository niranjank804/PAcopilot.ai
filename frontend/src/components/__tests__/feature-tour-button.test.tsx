/**
 * Per-page tours.
 *
 * Two properties matter. A page with no tour must render nothing —
 * that is what makes it safe to mount once in the shared header rather
 * than wiring it into every route. And finishing a feature tour must
 * not write onboarding state: it is help, not an introduction, so using
 * it should never mark someone as having been onboarded.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  pathname: "/chat",
  apiRequest: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/api-client", () => ({
  apiRequest: mocks.apiRequest,
  ApiError: class extends Error {},
  registerTokenAccessors: vi.fn(),
}));

import { FeatureTourButton } from "../feature-tour-button";
import { FEATURE_TOURS } from "@/lib/tour";

/** Feature tours point at page elements; without them every step is
 * skipped and the popover has nothing to anchor to. */
function giveStepsSomethingToPointAt(route: string) {
  for (const step of FEATURE_TOURS[route] ?? []) {
    const element = document.createElement("div");
    element.setAttribute("data-tour", step.target);
    element.getBoundingClientRect = () =>
      ({ top: 50, left: 10, width: 120, height: 30 }) as DOMRect;
    document.body.appendChild(element);
  }
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.pathname = "/chat";
  document.body.innerHTML = "";
});

describe("where it appears", () => {
  it("offers a tour on a page that has one", () => {
    render(<FeatureTourButton />);

    expect(
      screen.getByRole("button", { name: /take a tour of this page/i }),
    ).toBeInTheDocument();
  });

  it("renders nothing on a page that has none", () => {
    // Why it can live in the shared header without auditing routes.
    mocks.pathname = "/settings";

    const { container } = render(<FeatureTourButton />);

    expect(container).toBeEmptyDOMElement();
  });

  it("covers the feature areas the product leads with", () => {
    // Chat, model exploration, governance and reports — the four the
    // landing page and the global tour both point at.
    expect(Object.keys(FEATURE_TOURS).sort()).toEqual([
      "/chat",
      "/deployments",
      "/metadata",
      "/reports",
    ]);
  });
});

describe("running a feature tour", () => {
  it("shows this page's steps, not the global tour's", async () => {
    const user = userEvent.setup();
    giveStepsSomethingToPointAt("/chat");

    render(<FeatureTourButton />);
    await user.click(
      screen.getByRole("button", { name: /take a tour of this page/i }),
    );

    // The chat tour's first step, not "Your workspace".
    expect(
      await screen.findByRole("dialog", { name: /pick a specialist/i }),
    ).toBeInTheDocument();
  });

  it("counts only its own steps", async () => {
    const user = userEvent.setup();
    giveStepsSomethingToPointAt("/chat");

    render(<FeatureTourButton />);
    await user.click(
      screen.getByRole("button", { name: /take a tour of this page/i }),
    );

    expect(
      await screen.findByText(`Step 1 of ${FEATURE_TOURS["/chat"].length}`),
    ).toBeInTheDocument();
  });

  it("writes no onboarding state when finished", async () => {
    // A feature tour is help. Using it must not mark someone as having
    // completed the product introduction.
    const user = userEvent.setup();
    mocks.pathname = "/reports";
    giveStepsSomethingToPointAt("/reports");

    render(<FeatureTourButton />);
    await user.click(
      screen.getByRole("button", { name: /take a tour of this page/i }),
    );

    await user.click(await screen.findByRole("button", { name: /finish/i }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );

    expect(mocks.apiRequest).not.toHaveBeenCalled();
  });

  it("closes on skip without writing anything", async () => {
    const user = userEvent.setup();
    giveStepsSomethingToPointAt("/chat");

    render(<FeatureTourButton />);
    await user.click(
      screen.getByRole("button", { name: /take a tour of this page/i }),
    );
    await user.click(await screen.findByRole("button", { name: /skip tour/i }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );

    expect(mocks.apiRequest).not.toHaveBeenCalled();
  });
});

describe("the step data", () => {
  it("names only handles that pages actually tag", () => {
    // A step pointing at an untagged element is skipped silently, so
    // this is the check that keeps a tour from quietly explaining
    // nothing.
    const tagged = new Set([
      "chat-agent",
      "chat-input",
      "chat-history",
      "voice-input",
      "metadata-connection",
      "metadata-search",
      "governance-connection",
      "governance-changes",
      "governance-review",
      "reports-definitions",
    ]);

    for (const steps of Object.values(FEATURE_TOURS)) {
      for (const step of steps) {
        expect(tagged).toContain(step.target);
      }
    }
  });

  it("keeps each tour short enough to finish", () => {
    // A tour longer than the task it explains gets skipped.
    for (const steps of Object.values(FEATURE_TOURS)) {
      expect(steps.length).toBeLessThanOrEqual(5);
      expect(steps.length).toBeGreaterThan(0);
    }
  });
});
