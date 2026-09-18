import { expect, test } from "@playwright/test";

import { signIn, stubApi } from "./fixtures/stub-api";

/**
 * The authenticated app in a real browser, against a stubbed API.
 *
 * These are the checks a mocked DOM cannot make. The first one exists
 * because of a real defect: the page tour's spotlight was drawn 256px
 * to the right of the control it described. happy-dom has no layout, so
 * only a browser can say where a fixed-position overlay actually landed.
 */

test.beforeEach(async ({ context }) => {
  await stubApi(context);
  await signIn(context);
});

test("the page tour highlights the control it describes", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name === "mobile",
    "The chat tour targets desktop controls.",
  );

  await page.goto("/chat");
  await page.getByRole("button", { name: "Take a tour of this page" }).click();

  // Step 3 is the microphone.
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByRole("dialog")).toContainText("Or dictate it");

  // The overlay is four dimming panels around a hole. If the hole is
  // where the microphone is, the topmost element at the microphone's
  // centre is the microphone; if the spotlight is off by any amount, it
  // is a panel.
  const mic = page.locator('[data-tour="voice-input"]');
  const box = (await mic.boundingBox())!;
  const hit = await page.evaluate(
    ({ x, y }) => {
      const element = document.elementFromPoint(x, y);
      return {
        isMic: Boolean(element?.closest('[data-tour="voice-input"]')),
        // Named in the failure, so a regression says what covered it.
        description: element
          ? `${element.tagName.toLowerCase()} ${element.getAttribute("role") ?? ""} ${element.className}`.trim()
          : "nothing",
      };
    },
    { x: box.x + box.width / 2, y: box.y + box.height / 2 },
  );

  expect(hit.isMic, `covered by: ${hit.description}`).toBe(true);
});

test("sidebar entries explain themselves on hover", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name === "mobile",
    "The sidebar is a drawer on a phone; hover does not apply.",
  );

  await page.goto("/dashboard");
  await page.getByRole("link", { name: "Deployments" }).hover();

  await expect(page.getByRole("tooltip")).toContainText(
    "Nothing reaches TM1 until someone with deploy rights executes it",
  );
});

test("the same help reaches keyboard users", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "Keyboard focus test.");

  await page.goto("/dashboard");
  await page.getByRole("button", { name: "About Tool success rate" }).focus();

  await expect(page.getByRole("tooltip")).toContainText(
    "the share that returned a result",
  );
});

test("the dashboard shows measured numbers, not placeholders", async ({
  page,
}) => {
  await page.goto("/dashboard");

  // 117 calls, 4 errors → 96.6%, from the tool fixture.
  await expect(page.getByText("96.6%")).toBeVisible();
  await expect(page.getByText("1,842,310")).toBeVisible();
});

test("an engineering task selects its agent without sending", async ({
  page,
}) => {
  await page.goto("/chat");

  await page.getByRole("button", { name: "Generate TI" }).click();

  await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue(
    "Generate a TurboIntegrator process that ",
  );
  await expect(page.getByLabel("Agent")).toContainText("TI");
});
