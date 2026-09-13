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

/**
 * Security response headers.
 *
 * Access and refresh tokens live in localStorage, which means any script
 * that executes on this origin can read them. A Content-Security-Policy
 * is therefore not decoration here — it is the control that limits which
 * scripts can run at all, and where anything they collect could be sent.
 *
 * connect-src is derived from NEXT_PUBLIC_API_URL rather than hardcoded:
 * the API lives on a different origin to this app, so a policy that
 * omitted it would block every request the product makes. Only the
 * origin is taken, since CSP matches on origin and a path would be
 * ignored.
 */
function apiOrigin(): string {
  const raw = process.env.NEXT_PUBLIC_API_URL;

  if (!raw) return '';

  try {
    return new URL(raw).origin;
  } catch {
    // A malformed value is the build guard above's problem, not this
    // function's — degrade to an empty entry rather than failing here.
    return '';
  }
}

const securityHeaders = [
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  {
    key: 'Permissions-Policy',
    // The chat page uses the Web Speech API for dictation, which needs
    // the microphone; camera and geolocation are never used.
    value: 'camera=(), geolocation=(), microphone=(self)',
  },
  {
    key: 'Content-Security-Policy',
    value: [
      "default-src 'self'",
      // Next.js injects inline bootstrap scripts and, in development,
      // relies on eval for fast refresh.
      process.env.NODE_ENV === 'development'
        ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
        : "script-src 'self' 'unsafe-inline'",
      // Tailwind and the component library emit inline styles.
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data: blob:",
      "font-src 'self' data:",
      ["connect-src 'self'", apiOrigin()].filter(Boolean).join(' '),
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
      "object-src 'none'",
    ].join('; '),
  },
];

const nextConfig: NextConfig = {
  async headers() {
    return [{ source: '/:path*', headers: securityHeaders }];
  },
};

export default nextConfig;
