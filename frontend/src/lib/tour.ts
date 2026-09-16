"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * The product tour's data and state, separate from how it is drawn.
 *
 * Steps are declarative and target `data-tour` attributes rather than
 * class names or DOM positions. Classes here are Tailwind utilities
 * that change whenever someone restyles a card, and coordinates are
 * wrong the moment a viewport differs — a tour pinned to either breaks
 * silently, pointing at nothing while still looking like it works.
 *
 * A step whose target is absent is **skipped, not faked**. That is what
 * makes the tour safe to run for every role: a Viewer has no Users
 * page, so the element is not in their DOM and the step does not exist
 * for them. Nothing here needs its own copy of the permission rules,
 * which would be a second place for them to drift from the backend's.
 */

export interface TourStep {
  /** Matches `data-tour="..."` on the element to highlight. */
  target: string;
  title: string;
  body: string;
  /** Navigate here first. Omitted when the target is always present. */
  route?: string;
}

/**
 * The global tour: what the product is, in the order a new user meets
 * it. Every step points at something that exists today — no roadmap
 * entries, and nothing the capability registry marks PLANNED.
 */
export const PRODUCT_TOUR: TourStep[] = [
  {
    target: "nav-dashboard",
    route: "/dashboard",
    title: "Your workspace",
    body: "Everything starts here. The sidebar holds each part of PA-Copilot — this tour visits the ones you will use first.",
  },
  {
    target: "nav-connections",
    route: "/dashboard",
    title: "Connect Planning Analytics",
    body: "Register a TM1 or Planning Analytics server. Credentials are encrypted before they are stored, and the connection is scoped to your organization.",
  },
  {
    target: "nav-chat",
    route: "/dashboard",
    title: "Ask PA-Copilot",
    body: "Ask about cubes, rules, processes or errors in plain English. Specialist agents bring live TM1 tools to the conversation.",
  },
  {
    target: "voice-input",
    route: "/chat",
    title: "Or ask out loud",
    body: "Dictate a question instead of typing it. The transcript lands in the box for you to check before sending — and follows exactly the same permission and approval rules.",
  },
  {
    target: "nav-knowledge",
    route: "/dashboard",
    title: "Ground answers in your documents",
    body: "Upload your own documentation so answers cite your material rather than generic TM1 advice.",
  },
  {
    target: "nav-standards",
    route: "/dashboard",
    title: "Teach it your house style",
    body: "Upload exported TurboIntegrator processes and PA-Copilot measures how your team actually writes TM1, then follows what it finds.",
  },
  {
    target: "nav-metadata",
    route: "/dashboard",
    title: "Explore the model",
    body: "Walk the dependency graph across cubes, dimensions, processes and rules — including what an object's change would affect.",
  },
  {
    target: "nav-deployments",
    route: "/dashboard",
    title: "Nothing is written without you",
    body: "AI-drafted rule and process changes wait here as drafts with their impact analysis. A person reviews and executes; the assistant never writes to TM1 on its own.",
  },
  {
    target: "help-menu",
    route: "/dashboard",
    title: "Restart this any time",
    body: "This tour lives under Help. That is also where you will find it again after you finish.",
  },
];

/** Where the highlighted element sits, in page coordinates. */
export interface Spotlight {
  top: number;
  left: number;
  width: number;
  height: number;
}

export function measure(target: string): Spotlight | null {
  const element = document.querySelector(`[data-tour="${target}"]`);

  if (!element) return null;

  const rect = element.getBoundingClientRect();

  // A zero-size box means the element is in the DOM but not laid out —
  // a collapsed sidebar on mobile, or a node inside a closed section.
  // Highlighting it would draw a marker over nothing.
  if (rect.width === 0 && rect.height === 0) return null;

  return {
    top: rect.top + window.scrollY,
    left: rect.left + window.scrollX,
    width: rect.width,
    height: rect.height,
  };
}

export function useTour(steps: TourStep[] = PRODUCT_TOUR) {
  const [index, setIndex] = useState<number | null>(null);
  const [spotlight, setSpotlight] = useState<Spotlight | null>(null);

  const isRunning = index !== null;
  const step = isRunning ? (steps[index] ?? null) : null;

  const start = useCallback(() => setIndex(0), []);
  const stop = useCallback(() => {
    setIndex(null);
    setSpotlight(null);
  }, []);

  const next = useCallback(
    () =>
      setIndex((current) => {
        if (current === null) return null;
        return current + 1 >= steps.length ? null : current + 1;
      }),
    [steps.length],
  );

  const back = useCallback(
    () => setIndex((current) => (current === null ? null : Math.max(0, current - 1))),
    [],
  );

  // Re-measure on scroll and resize: the popover is positioned from the
  // element's real box, so a tour that measured once would drift away
  // from its target the moment anything moved.
  useEffect(() => {
    if (!step) return;

    let frame = 0;

    const update = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => setSpotlight(measure(step.target)));
    };

    const element = document.querySelector(`[data-tour="${step.target}"]`);

    element?.scrollIntoView({ block: "center", behavior: "smooth" });
    update();

    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);

    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [step]);

  return { isRunning, index, step, steps, spotlight, start, stop, next, back };
}
