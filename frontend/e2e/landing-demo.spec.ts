import { expect, test } from "@playwright/test";

/**
 * The demo replays in a real browser: it starts when scrolled into view,
 * reaches the end of the transcript, and switching scenarios works. The
 * IntersectionObserver trigger is exactly what happy-dom cannot exercise.
 */

test("the demo replays when scrolled into view", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("link", { name: /See a demo/ }).click();

  const panel = page.getByRole("tabpanel");
  const lastStep = panel.getByRole("listitem").last();

  // Four steps at 1.1s each is under five seconds; eight leaves room for a
  // slow CI machine.
  await expect(lastStep).not.toHaveAttribute("aria-hidden", "true", {
    timeout: 8_000,
  });

  await page.getByRole("tab", { name: /Chart a question/ }).click();
  await expect(
    panel.getByRole("img", { name: /Bar chart, sample data/ }),
  ).toBeVisible({ timeout: 8_000 });
});
