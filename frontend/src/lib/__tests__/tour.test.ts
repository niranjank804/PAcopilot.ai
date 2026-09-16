/**
 * Tour steps and measurement.
 *
 * The behaviour worth pinning is that a step pointing at nothing is
 * *skipped* rather than drawn somewhere arbitrary. That is what lets
 * one tour serve every role: a Viewer has no Users nav item, so the
 * element is absent and the step does not exist for them — without the
 * tour needing its own copy of the permission rules to drift from the
 * backend's.
 */

import { afterEach, describe, expect, it } from "vitest";

import { PRODUCT_TOUR, measure } from "../tour";

afterEach(() => {
  document.body.innerHTML = "";
});

describe("tour steps", () => {
  it("targets data-tour handles, never classes or positions", () => {
    // A class is a styling decision someone will change; a coordinate is
    // wrong on the next viewport. Either breaks the tour silently.
    for (const step of PRODUCT_TOUR) {
      expect(step.target).toMatch(/^[a-z0-9-]+$/);
    }
  });

  it("gives every step something to say", () => {
    for (const step of PRODUCT_TOUR) {
      expect(step.title.length).toBeGreaterThan(0);
      expect(step.body.length).toBeGreaterThan(20);
    }
  });

  it("uses each handle only once", () => {
    // Two steps on one element would highlight the same box twice and
    // read as a bug.
    const handles = PRODUCT_TOUR.map((step) => step.target);

    expect(new Set(handles).size).toBe(handles.length);
  });

  it("routes only to real application paths", () => {
    const routes = PRODUCT_TOUR.map((step) => step.route).filter(Boolean);

    for (const route of routes) {
      expect(route).toMatch(/^\/[a-z-]+$/);
    }
  });

  it("covers governance, since that is the product's core claim", () => {
    // "A human approves before anything is written" is the promise the
    // product makes; a tour that never mentions it undersells the one
    // thing that distinguishes it.
    const bodies = PRODUCT_TOUR.map((step) => step.body.toLowerCase()).join(" ");

    expect(bodies).toContain("review");
    expect(bodies).toMatch(/never writes|approval|before anything is written/);
  });
});

describe("measure", () => {
  it("returns null for an element that is not there", () => {
    // The skip-rather-than-fake property.
    expect(measure("nav-does-not-exist")).toBeNull();
  });

  it("returns null for an element with no layout", () => {
    // In the DOM but collapsed — a hidden mobile sidebar. Highlighting
    // it would draw a marker over nothing.
    const hidden = document.createElement("div");
    hidden.setAttribute("data-tour", "collapsed");
    document.body.appendChild(hidden);

    expect(measure("collapsed")).toBeNull();
  });

  it("measures an element that is laid out", () => {
    const element = document.createElement("div");
    element.setAttribute("data-tour", "nav-chat");
    element.getBoundingClientRect = () =>
      ({ top: 100, left: 20, width: 200, height: 40 }) as DOMRect;
    document.body.appendChild(element);

    expect(measure("nav-chat")).toEqual({
      top: 100,
      left: 20,
      width: 200,
      height: 40,
    });
  });

  it("reports page coordinates, not viewport ones", () => {
    // The overlay is absolutely positioned on the page, so a scrolled
    // viewport would otherwise put the spotlight in the wrong place.
    const element = document.createElement("div");
    element.setAttribute("data-tour", "scrolled");
    element.getBoundingClientRect = () =>
      ({ top: 10, left: 5, width: 100, height: 20 }) as DOMRect;
    document.body.appendChild(element);

    window.scrollY = 500;
    window.scrollX = 30;

    const spotlight = measure("scrolled");

    expect(spotlight?.top).toBe(510);
    expect(spotlight?.left).toBe(35);

    window.scrollY = 0;
    window.scrollX = 0;
  });
});
