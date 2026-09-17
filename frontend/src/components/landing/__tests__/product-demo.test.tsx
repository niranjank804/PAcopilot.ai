/**
 * The landing-page demo.
 *
 * The honesty checks matter most. A demo is where a product is most
 * tempted to show things it cannot do, so the tool names it displays are
 * checked against the tools the backend actually registers: rename or
 * remove a tool there and this fails until the demo is corrected.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DEMO_SCENARIOS, ProductDemo } from "../product-demo";

const TOOLS_DIR = resolve(__dirname, "../../../../../backend/src/ai/tools");

function registeredToolNames(dir: string): Set<string> {
  const names = new Set<string>();

  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);

    if (statSync(path).isDirectory()) {
      registeredToolNames(path).forEach((name) => names.add(name));
    } else if (entry.endsWith(".py")) {
      for (const match of readFileSync(path, "utf8").matchAll(
        /^\s+name\s*=\s*"([a-z_]+)"/gm,
      )) {
        names.add(match[1]);
      }
    }
  }

  return names;
}

function steps() {
  return within(screen.getByRole("tabpanel")).getAllByRole("listitem", {
    hidden: true,
  });
}

function shownCount() {
  return steps().filter((step) => step.getAttribute("aria-hidden") !== "true")
    .length;
}

describe("demo content", () => {
  it("only shows tools the backend really has", () => {
    const real = registeredToolNames(TOOLS_DIR);
    // Guards the guard: an empty set would make every check below pass.
    expect(real.size).toBeGreaterThan(10);

    const shown = DEMO_SCENARIOS.flatMap((scenario) =>
      scenario.steps.flatMap((step) => (step.kind === "tool" ? [step.tool] : [])),
    );

    expect(shown.length).toBeGreaterThan(0);
    for (const tool of shown) {
      expect(real, `demo shows "${tool}"`).toContain(tool);
    }
  });

  it("says it is sample data, not a live environment", () => {
    render(<ProductDemo />);

    expect(screen.getByText(/sample Sales model/i)).toBeInTheDocument();
  });

  it("shows the AI drafting and a person executing, never the AI deploying", () => {
    render(<ProductDemo />);
    fireEvent.click(screen.getByRole("tab", { name: /Draft the fix/ }));

    expect(screen.getByText("Awaiting review")).toBeInTheDocument();
    expect(
      screen.getByText(/Only a person with deploy rights can execute this/),
    ).toBeInTheDocument();
  });
});

describe("replay", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("renders the whole first transcript before any replay starts", () => {
    // What the server sends and what a reader without JavaScript keeps.
    render(<ProductDemo />);

    expect(shownCount()).toBe(DEMO_SCENARIOS[0].steps.length);
  });

  it("steps through a scenario one message at a time", () => {
    render(<ProductDemo />);

    fireEvent.click(screen.getByRole("tab", { name: /Chart a question/ }));
    expect(shownCount()).toBe(1);

    act(() => vi.advanceTimersByTime(1100));
    expect(shownCount()).toBe(2);

    // One step per act: each timer is scheduled by the render the previous
    // one caused, so a single large jump would only ever advance one step.
    for (let i = 0; i < 10; i += 1) {
      act(() => vi.advanceTimersByTime(1100));
    }
    expect(shownCount()).toBe(DEMO_SCENARIOS[2].steps.length);
    expect(screen.getByRole("button", { name: /Replay/ })).toBeEnabled();
  });

  it("skips the animation for someone who prefers reduced motion", () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockReturnValue({ matches: true, addEventListener: vi.fn() }),
    );
    render(<ProductDemo />);

    fireEvent.click(screen.getByRole("tab", { name: /Draft the fix/ }));

    expect(shownCount()).toBe(DEMO_SCENARIOS[1].steps.length);
  });

  it("moves between scenarios with the arrow keys", () => {
    render(<ProductDemo />);

    fireEvent.keyDown(screen.getByRole("tab", { name: /Diagnose a rule/ }), {
      key: "ArrowRight",
    });

    expect(screen.getByRole("tab", { name: /Draft the fix/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});
