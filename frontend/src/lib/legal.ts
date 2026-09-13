/**
 * Identity shown on the legal pages.
 *
 * Deliberately env-driven and deliberately unset by default. Privacy and
 * terms documents name a legal entity, a contact address and a governing
 * jurisdiction; inventing plausible-looking values for those would be
 * worse than showing nothing, because a wrong entity name on a published
 * privacy policy is a misrepresentation rather than a cosmetic gap.
 *
 * Anything unset renders as a visible placeholder, so an unconfigured
 * deployment is obvious on the page instead of silently shipping blanks.
 */

export const legalIdentity = {
  entity: process.env.NEXT_PUBLIC_LEGAL_ENTITY ?? null,
  email: process.env.NEXT_PUBLIC_LEGAL_EMAIL ?? null,
  address: process.env.NEXT_PUBLIC_LEGAL_ADDRESS ?? null,
  jurisdiction: process.env.NEXT_PUBLIC_LEGAL_JURISDICTION ?? null,
} as const;

export const legalIdentityIsConfigured = Object.values(legalIdentity).every(
  (value) => value !== null && value !== "",
);

/** The last time the wording below was reviewed, not the build date. */
export const legalLastUpdated = "2026-09-13";
