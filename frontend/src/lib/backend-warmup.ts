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

/** Seconds since `active` became true; 0 while it is false. Shown next
 * to the wake-up notice so a cold start reads as progress, not a hang. */
export function useElapsedSeconds(active: boolean): number {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!active) return;

    const started = Date.now();
    const timer = setInterval(
      () => setElapsed(Math.round((Date.now() - started) / 1000)),
      1000,
    );

    return () => {
      clearInterval(timer);
      setElapsed(0);
    };
  }, [active]);

  return active ? elapsed : 0;
}

/** Between pings, comfortably inside the free instance's 15-minute idle
 * limit. */
const KEEP_AWAKE_INTERVAL_MS = 10 * 60_000;

/**
 * Keep the backend awake for as long as the app is open.
 *
 * Reading an answer or a report for twenty minutes counts as idle to the
 * hosting, and the next click then waits a minute for a cold start. A
 * request every ten minutes from an open, visible tab prevents that for
 * the length of a working session. It does nothing for the first visit
 * of the day — only an external monitor or a paid instance can.
 */
export function useKeepAwake(): void {
  useEffect(() => {
    const ping = () => {
      // A background tab is not a session; let the instance sleep.
      if (document.visibilityState !== "visible") return;

      fetch(`${API_URL}/health`, { mode: "no-cors", cache: "no-store" }).catch(
        () => {
          // Nothing to do: the next real request will report any outage.
        },
      );
    };

    const timer = setInterval(ping, KEEP_AWAKE_INTERVAL_MS);

    return () => clearInterval(timer);
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
