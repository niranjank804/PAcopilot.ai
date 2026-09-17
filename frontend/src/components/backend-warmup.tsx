"use client";

import { useBackendWarmup } from "@/lib/backend-warmup";

/** Lets a server-rendered page start waking the backend. Renders nothing. */
export function BackendWarmup() {
  useBackendWarmup();

  return null;
}
