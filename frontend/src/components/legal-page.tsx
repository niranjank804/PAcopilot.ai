import Link from "next/link";

import {
  legalIdentity,
  legalIdentityIsConfigured,
  legalLastUpdated,
} from "@/lib/legal";

/** A value that has not been configured, shown rather than hidden. */
function Missing({ name }: { name: string }) {
  return (
    <span className="rounded bg-destructive/10 px-1 font-mono text-xs text-destructive">
      [set {name}]
    </span>
  );
}

export function LegalValue({
  value,
  envVar,
}: {
  value: string | null;
  envVar: string;
}) {
  return value ? <>{value}</> : <Missing name={envVar} />;
}

export function LegalPage({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <Link
        href="/"
        className="text-sm text-muted-foreground hover:text-foreground"
      >
        ← Back
      </Link>

      <h1 className="mt-6 text-3xl font-semibold">{title}</h1>

      <p className="mt-2 text-sm text-muted-foreground">
        Last updated {legalLastUpdated}
      </p>

      {!legalIdentityIsConfigured ? (
        <div className="mt-6 rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm">
          <strong>This page is not fully configured.</strong> The
          highlighted values below come from environment variables and are
          unset in this deployment. This document is a starting point that
          has not been reviewed by a lawyer — treat it as a draft until it
          has been.
        </div>
      ) : null}

      <div className="mt-8 space-y-6 text-sm leading-relaxed [&_h2]:mt-8 [&_h2]:text-lg [&_h2]:font-semibold [&_li]:ml-5 [&_li]:list-disc">
        {children}
      </div>

      <hr className="my-10 border-border" />

      <p className="text-sm text-muted-foreground">
        Questions about this page:{" "}
        <LegalValue
          value={legalIdentity.email}
          envVar="NEXT_PUBLIC_LEGAL_EMAIL"
        />
      </p>
    </main>
  );
}
