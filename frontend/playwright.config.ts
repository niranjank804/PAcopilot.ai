import { defineConfig, devices } from "@playwright/test";

/**
 * Real-browser checks, kept deliberately narrow.
 *
 * The unit tests run in happy-dom, where `getBoundingClientRect` is
 * whatever the test says it is. That is fine for logic and useless for
 * layout: it cannot tell you whether the tour popover actually lands on
 * screen, or whether a page overflows sideways on a phone. Those are
 * the questions this config exists to answer, and nothing else — the
 * behavioural suite stays in vitest, where it is faster.
 *
 * Chromium only. Adding browsers multiplies CI time for a suite whose
 * subject is layout arithmetic, not engine differences, and the voice
 * features are Chromium-family anyway.
 *
 * The server is started here rather than assumed, so the suite cannot
 * pass against a stale build someone left running.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "line" : "list",

  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "on-first-retry",
  },

  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    // The viewport the previous round could not verify.
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],

  webServer: {
    // A production build: `next dev` serves different HTML and would
    // not catch a layout problem that only appears once compiled.
    command: "npm run build && npm run start -- --port 3100",
    url: "http://127.0.0.1:3100",
    reuseExistingServer: !process.env.CI,
    timeout: 300_000,
    env: {
      // The build guard refuses to run without this, by design.
      NEXT_PUBLIC_API_URL: "http://127.0.0.1:3101",
    },
  },
});
