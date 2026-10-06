/**
 * Per-page tours.
 *
 * Two properties matter. A page with no tour must render nothing —
 * that is what makes it safe to mount once in the shared header rather
 * than wiring it into every route. And finishing a feature tour must
 * not write onboarding state: it is help, not an introduction, so using
 * it should never mark someone as having been onboarded.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

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
import { FEATURE_TOURS, PRODUCT_TOUR, featureTourFor } from "@/lib/tour";

const SRC = resolve(__dirname, "../..");

/** Every `data-tour="..."` handle written in the app's source, tests excluded. */
function taggedHandles(dir = SRC, found = new Set<string>()): Set<string> {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      if (entry !== "__tests__" && entry !== "node_modules") taggedHandles(path, found);
    } else if (/\.tsx?$/.test(entry)) {
      const text = readFileSync(path, "utf8");
      for (const match of text.matchAll(/data-tour="([a-z0-9-]+)"/g)) found.add(match[1]);
      for (const match of text.matchAll(/\btour(?:: |=)"([a-z0-9-]+)"/g)) found.add(match[1]);
    }
  }
  return found;
}

/** The app's page routes, from the folders under app/(app). */
function appRoutes(dir = join(SRC, "app", "(app)"), prefix = ""): string[] {
  const routes: string[] = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (!statSync(path).isDirectory() || entry === "__tests__") continue;
    const route = `${prefix}/${entry}`;
    if (readdirSync(path).includes("page.tsx")) routes.push(route);
    routes.push(...appRoutes(path, route));
  }
  return routes;
}

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
    mocks.pathname = "/no-such-page";

    const { container } = render(<FeatureTourButton />);

    expect(container).toBeEmptyDOMElement();
  });

  it("has a tour for every page in the app", () => {
    for (const route of appRoutes()) {
      expect(featureTourFor(route), route).toBeDefined();
    }
  });

  it("uses a detail page's shared tour for any id", () => {
    expect(featureTourFor("/team/abc-123")).toBe(FEATURE_TOURS["/team/[id]"]);
    expect(featureTourFor("/team/abc/extra")).toBeUndefined();
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

    // The chat tour's first step, not the global tour's "Command Center".
    expect(
      await screen.findByRole("dialog", { name: FEATURE_TOURS["/chat"][0].title }),
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

    for (let step = 1; step < FEATURE_TOURS["/reports"].length; step++) {
      await user.click(await screen.findByRole("button", { name: /next/i }));
    }
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
    const tagged = taggedHandles();

    expect(tagged.size).toBeGreaterThan(20);
    for (const step of [...PRODUCT_TOUR, ...Object.values(FEATURE_TOURS).flat()]) {
      expect(tagged, step.target).toContain(step.target);
    }
  });

  it("keeps each tour short enough to finish", () => {
    // Every option is explained, but related controls share a step: a
    // tour longer than the task it explains gets skipped.
    for (const steps of Object.values(FEATURE_TOURS)) {
      expect(steps.length).toBeLessThanOrEqual(16);
      expect(steps.length).toBeGreaterThan(0);
    }
  });
});
