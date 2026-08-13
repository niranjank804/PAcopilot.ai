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
 */
if (process.env.VERCEL && !process.env.NEXT_PUBLIC_API_URL) {
  throw new Error(
    "NEXT_PUBLIC_API_URL is not set.\n\n" +
      "Add it in Vercel under Settings > Environment Variables, pointing " +
      "at the backend, e.g. https://pa-copilot-backend.onrender.com\n\n" +
      "Without it this build would ship pointing at http://localhost:8000 " +
      "and every API call would fail in the browser.",
  );
}

const nextConfig: NextConfig = {
  /* config options here */
};

export default nextConfig;
