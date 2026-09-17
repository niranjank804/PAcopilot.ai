import { expect, test } from "@playwright/test";

/**
 * Sign In With Google must survive the Content-Security-Policy.
 *
 * The policy once shipped without Google's origins and the button
 * vanished from the live login page. Nothing failed loudly: the page
 * rendered, the "or" divider rendered, and the browser quietly refused
 * the script that draws the button. Only a real browser enforcing the
 * real headers can see that, so this is where it is checked.
 *
 * The webServer in playwright.config.ts builds with a placeholder client
 * ID so the Google branch of the login page is actually rendered.
 */

test("the login page's CSP allows Google Identity Services", async ({
  request,
}) => {
  const response = await request.get("/login");
  const csp = response.headers()["content-security-policy"] ?? "";

  const directive = (name: string) =>
    csp
      .split(";")
      .map((part) => part.trim())
      .find((part) => part.startsWith(`${name} `)) ?? "";

  expect(directive("script-src")).toContain(
    "https://accounts.google.com/gsi/client",
  );
  expect(directive("style-src")).toContain(
    "https://accounts.google.com/gsi/style",
  );
  expect(directive("connect-src")).toContain("https://accounts.google.com/gsi/");
  // Without frame-src the button's iframe falls back to default-src
  // 'self' and is blocked.
  expect(directive("frame-src")).toContain("https://accounts.google.com/gsi/");
});

test("the browser reports no CSP violation on the login page", async ({
  page,
}) => {
  const violations: string[] = [];

  // Chromium reports a blocked resource as a console error. Listening
  // for the violation, not for the button, keeps the test independent
  // of whether Google itself is reachable from the machine running it.
  page.on("console", (message) => {
    if (message.text().includes("Content Security Policy")) {
      violations.push(message.text());
    }
  });

  await page.goto("/login");
  await page.waitForLoadState("networkidle");

  expect(violations).toEqual([]);
});
