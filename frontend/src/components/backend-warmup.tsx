"use client";

import { useBackendWarmup, useKeepAwake } from "@/lib/backend-warmup";

/** Lets a server-rendered page start waking the backend. Renders nothing. */
export function BackendWarmup() {
  useBackendWarmup();

  return null;
}

/** Mounted once in the authenticated shell. Renders nothing. */
export function KeepAwake() {
  useKeepAwake();

  return null;
}
