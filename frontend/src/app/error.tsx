"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/button";

/**
 * Route-level error boundary.
 *
 * Two very different failures land here and they need different handling.
 *
 * A *chunk load error* means the browser is holding an HTML document from
 * the previous deployment and is asking for a JavaScript bundle whose
 * filename no longer exists. Nothing is broken — the tab is simply stale.
 * Reloading fetches the current document and the error disappears, so
 * this component reloads once automatically rather than showing a
 * failure the user can do nothing useful about. The sessionStorage flag
 * stops that becoming a reload loop if the reload does not fix it.
 *
 * Anything else is a real application error, and gets a message plus a
 * retry that re-renders the segment without a full navigation.
 */

const RELOAD_FLAG = "pa-copilot-chunk-reload";

function isChunkLoadError(error: Error): boolean {
  return (
    error.name === "ChunkLoadError" ||
    /Loading chunk [\w-]+ failed/i.test(error.message) ||
    /Failed to fetch dynamically imported module/i.test(error.message) ||
    /error loading dynamically imported module/i.test(error.message)
  );
}

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    if (!isChunkLoadError(error)) {
      console.error(error);
      return;
    }

    let alreadyReloaded = false;

    try {
      alreadyReloaded = sessionStorage.getItem(RELOAD_FLAG) === "1";

      if (!alreadyReloaded) {
        sessionStorage.setItem(RELOAD_FLAG, "1");
      }
    } catch {
      // Private browsing or blocked storage: fall through and show the
      // message rather than risking an unbounded reload loop.
      return;
    }

    if (!alreadyReloaded) {
      window.location.reload();
    }
  }, [error]);

  // Clear the guard once a render succeeds, so a genuine stale-chunk
  // error after the next deploy can auto-recover too.
  useEffect(() => {
    return () => {
      try {
        sessionStorage.removeItem(RELOAD_FLAG);
      } catch {
        // Nothing to clean up if storage is unavailable.
      }
    };
  }, []);

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-8 text-center">
      <h2 className="text-xl font-semibold">Something went wrong</h2>

      <p className="max-w-md text-sm text-muted-foreground">
        This page failed to load. Trying again often resolves it; if it
        keeps happening, a full browser reload usually will.
      </p>

      {error.digest ? (
        <p className="text-xs text-muted-foreground">
          Reference: <code>{error.digest}</code>
        </p>
      ) : null}

      <div className="flex gap-2">
        <Button onClick={reset}>Try again</Button>
        <Button variant="outline" onClick={() => window.location.reload()}>
          Reload page
        </Button>
      </div>
    </div>
  );
}
