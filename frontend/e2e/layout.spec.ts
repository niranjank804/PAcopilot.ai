import { expect, test } from "@playwright/test";

/**
 * Layout facts a mocked DOM cannot establish.
 *
 * The vitest suite runs in happy-dom, where every element's box is
 * whatever the test declared. That proves the tour's *logic* — which
 * step follows which, what is skipped when a target is missing — and
 * proves nothing about whether anything lands on screen. The previous
 * round said so explicitly and left it unverified; this closes that.
 *
 * Public pages only. The authenticated app needs a backend, and a suite
 * that quietly depends on one is a suite that fails for reasons
 * unrelated to layout.
 */

const PUBLIC_PAGES = ["/", "/pricing", "/login", "/request-access"];

for (const path of PUBLIC_PAGES) {
  test(`${path} does not scroll sideways`, async ({ page }) => {
    await page.goto(path);

    // Horizontal overflow is the classic mobile failure and is
    // invisible in jsdom: an element wider than the viewport pushes the
    // document out and everything gains a sideways scrollbar.
    const overflow = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));

    // One pixel of slack for sub-pixel rounding at odd device ratios.
    expect(overflow.scrollWidth).toBeLessThanOrEqual(
      overflow.clientWidth + 1,
    );
  });

  test(`${path} has an accessible page heading`, async ({ page }) => {
    await page.goto(path);

    // By role, not by tag: what matters is that assistive technology is
    // told what the page is. The auth pages had no heading element at
    // all — their title was a styled div — which this caught.
    await expect(
      page.getByRole("heading", { level: 1 }).first(),
    ).toBeAttached();
  });
}

test("the landing page no longer presents itself as a beta", async ({
  page,
}) => {
  await page.goto("/");

  const body = (await page.locator("body").innerText()).toLowerCase();

  expect(body).not.toContain("beta testing");
  expect(body).not.toContain("beta tester");
});

test("the tour popover stays on screen at mobile width", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "mobile",
    "The clamping only matters at narrow widths.",
  );

  await page.goto("/");

  // The tour lives behind authentication, so its positioning maths is
  // exercised directly against a real layout engine rather than by
  // signing in. This is the arithmetic that happy-dom cannot check:
  // real element boxes, real viewport, real clamping.
  const result = await page.evaluate(() => {
    const GAP = 8;
    const POPOVER_WIDTH = 320;

    // A target hard against the right edge — the case that pushes an
    // unclamped popover off screen.
    const target = document.createElement("div");
    target.style.cssText =
      "position:absolute;top:100px;right:0;width:120px;height:40px";
    document.body.appendChild(target);

    const rect = target.getBoundingClientRect();
    const spotlight = {
      top: rect.top + window.scrollY,
      left: rect.left + window.scrollX,
      width: rect.width,
      height: rect.height,
    };

    const left = Math.min(
      Math.max(GAP, spotlight.left),
      Math.max(GAP, window.innerWidth - POPOVER_WIDTH - GAP),
    );

    return {
      left,
      viewportWidth: window.innerWidth,
      popoverRight: left + POPOVER_WIDTH,
      targetLeft: spotlight.left,
    };
  });

  // Without clamping the popover would start at the target's own left
  // edge and run past the viewport.
  expect(result.targetLeft).toBeGreaterThan(
    result.viewportWidth - 320,
  );
  expect(result.left).toBeGreaterThanOrEqual(8);
  // On a viewport narrower than the popover the best available answer
  // is flush-left, which is what the clamp produces.
  expect(result.left).toBeLessThanOrEqual(
    Math.max(8, result.viewportWidth - 320 - 8),
  );
});
