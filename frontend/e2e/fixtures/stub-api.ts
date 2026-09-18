import type { BrowserContext } from "@playwright/test";

/**
 * A stand-in for the backend, for testing the authenticated app.
 *
 * The build under test points NEXT_PUBLIC_API_URL at a port nothing
 * listens on (see playwright.config.ts); every request there is answered
 * from the fixtures below. That makes these tests about the frontend
 * only: layout, navigation, the tour, tooltips. Nothing here is real
 * data and none of it is shown anywhere but a test.
 */

export const API = "http://127.0.0.1:3101";

const ok = (data: unknown) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify({ success: true, data }),
});

const minutesAgo = (minutes: number) =>
  new Date(Date.now() - minutes * 60_000).toISOString();

const me = {
  id: "u1",
  username: "npatra",
  email: "n@example.com",
  first_name: "Niranjan",
  last_name: "Patra",
  is_active: true,
  organization_id: "o1",
  onboarding_completed_at: minutesAgo(10_000),
  onboarding_dismissed_at: null,
};

const AGENTS = [
  "administrator",
  "analyst",
  "architect",
  "developer",
  "documentation",
  "performance",
  "reviewer",
  "ti",
  "troubleshooter",
];

const fixtures: [RegExp, () => ReturnType<typeof ok>][] = [
  [/\/auth\/me$/, () => ok(me)],
  [
    /\/tm1\/connections$/,
    () =>
      ok([
        {
          id: "c1",
          name: "fpa",
          address: "us-east-1.planninganalytics.saas.ibm.com",
          port: 443,
          ssl: true,
          username: "apikey",
          is_active: true,
          authentication_type: "v12_saas",
          tenant: "TENANT",
          database: "BusinessFlow",
        },
      ]),
  ],
  [
    /\/monitoring\/usage/,
    () =>
      ok({
        total_requests: 128,
        total_tokens: 1_842_310,
        total_cost_usd: 14.62,
        cache_hit_rate: 0.41,
        cache_read_tokens: 700_000,
        cache_creation_tokens: 120_000,
        by_model: [
          {
            model: "claude-sonnet-5",
            requests: 128,
            total_tokens: 1_842_310,
            total_cost_usd: 14.62,
          },
        ],
      }),
  ],
  [
    /\/monitoring\/tools/,
    () =>
      ok([
        {
          tool_name: "get_process",
          total_calls: 61,
          success_count: 60,
          error_count: 1,
          not_found_count: 0,
          avg_duration_ms: 840,
        },
        {
          tool_name: "find_dependencies",
          total_calls: 56,
          success_count: 53,
          error_count: 3,
          not_found_count: 0,
          avg_duration_ms: 95,
        },
      ]),
  ],
  [
    /\/monitoring\/tm1-status/,
    () => ok([{ connection_id: "c1", name: "fpa", state: "closed", failure_count: 0 }]),
  ],
  [
    /\/ai\/conversations$/,
    () =>
      ok([
        {
          id: "k1",
          title: "Explain IT_Load Data",
          created_at: minutesAgo(60),
          updated_at: minutesAgo(4),
        },
      ]),
  ],
  [
    /\/ai\/agents$/,
    () =>
      ok(
        AGENTS.map((name) => ({
          name,
          description: `${name} agent`,
          max_tool_rounds: 8,
          tool_names: ["get_process"],
          safety_notes: null,
        })),
      ),
  ],
];

/** Answer every API request from the fixtures; unknown paths get an
 * empty list, which every list-shaped screen tolerates. */
export async function stubApi(context: BrowserContext): Promise<void> {
  await context.route(`${API}/**`, (route) => {
    const path = route.request().url().replace(API, "");
    const hit = fixtures.find(([pattern]) => pattern.test(path));

    return route.fulfill(hit ? hit[1]() : ok([]));
  });
}

/** Tokens in localStorage are what the auth context reads on boot. The
 * values are never sent anywhere real: the API above is the stub. */
export async function signIn(context: BrowserContext): Promise<void> {
  await context.addInitScript(() => {
    window.localStorage.setItem(
      "pa-copilot-tokens",
      JSON.stringify({ accessToken: "test", refreshToken: "test" }),
    );
  });
}
