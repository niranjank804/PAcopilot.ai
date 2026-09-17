"use client";

import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

let warmupStarted = false;

/**
 * Start waking the backend the moment someone lands on a public page.
 *
 * The backend runs on Render's free plan, which stops the process after
 * 15 idle minutes and takes a minute or more to bring it back. Without
 * this, that wait starts only when the user presses "Sign in" — after
 * they have already spent several seconds typing a password. Starting it
 * on arrival hands those seconds back.
 *
 * `no-cors` because nothing is read from the response: the request
 * reaching the server is the whole point, and an opaque response avoids
 * a CORS error in the console for a call nobody asked to see.
 */
export function warmBackend(): void {
  if (warmupStarted || typeof window === "undefined") return;

  warmupStarted = true;

  fetch(`${API_URL}/health`, { mode: "no-cors", cache: "no-store" }).catch(
    () => {
      // A sleeping or unreachable backend is exactly the case this exists
      // for; the real request will surface any error properly.
    },
  );
}

/** Fire the warm-up once per page load. */
export function useBackendWarmup(): void {
  useEffect(() => {
    warmBackend();
  }, []);
}

/**
 * True once `active` has stayed true for `afterMs`.
 *
 * Used to tell someone *why* sign-in is slow, but only when it actually
 * is: a warm backend answers in well under a second, and flashing a
 * "waking up" notice on every sign-in would be noise.
 */
export function useSlowFlag(active: boolean, afterMs = 4000): boolean {
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    if (!active) return;

    const timer = setTimeout(() => setSlow(true), afterMs);

    return () => {
      clearTimeout(timer);
      setSlow(false);
    };
  }, [active, afterMs]);

  return active && slow;
}
