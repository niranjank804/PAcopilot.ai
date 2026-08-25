import type { NextConfig } from "next";

/**
 * Fail a deployment build that has no API URL.
 *
 * NEXT_PUBLIC_* values are inlined at build time, and the app falls back
 * to http://localhost:8000 when the variable is missing. On a deployed
 * build that fallback is silently wrong in the worst way: the site loads
 * and looks fine, while every request goes to the *visitor's* own
 * machine and fails. There is nothing in the UI to suggest a
 * misconfiguration.
 *
 * Guarded on VERCEL (set automatically by Vercel) rather than on
 * NODE_ENV, because `next build` runs in production mode locally too and
 * a local production build with no API URL is perfectly legitimate.
 *
 * The variable has to exist in EVERY Vercel environment, not just
 * Production. Setting it for Production alone is the easy mistake — the
 * live site builds and works, and then every preview and pull request
 * build fails here instead, which reads as this guard being broken
 * rather than as configuration being incomplete. The message names the
 * environment it is actually running in so the two are distinguishable.
 */
if (process.env.VERCEL && !process.env.NEXT_PUBLIC_API_URL) {
  const environment = process.env.VERCEL_ENV ?? "unknown";

  throw new Error(
    `NEXT_PUBLIC_API_URL is not set for the "${environment}" environment.\n\n` +
      "Add it in Vercel under Settings > Environment Variables, pointing " +
      "at the backend, e.g. https://pa-copilot-backend.onrender.com\n\n" +
      "Tick Production, Preview AND Development. A value set for " +
      "Production only builds the live site fine and fails every preview " +
      "and pull request build here.\n\n" +
      "Without it this build would ship pointing at http://localhost:8000 " +
      "and every API call would fail in the browser.",
  );
}

const nextConfig: NextConfig = {
  /* config options here */
};

export default nextConfig;
