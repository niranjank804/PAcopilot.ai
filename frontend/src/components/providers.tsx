"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useEffect, useState, type ReactNode } from "react";
import { ApiError } from "@/lib/api-client";
import { AuthProvider } from "@/lib/auth-context";
import { Toaster } from "@/components/ui/sonner";

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Never re-ask a question the API answered definitively: an
            // ApiError means the backend responded (and TM1 calls are already
            // retried 4x server-side — client retries just multiply the wait,
            // leaving pages on skeletons for ~30s). Only retry once for
            // transport-level failures (fetch threw, no response at all).
            retry: (failureCount, error) =>
              !(error instanceof ApiError) && failureCount < 1,
            staleTime: 30_000,
            // The API is same-host; the default "online" networkMode pauses
            // queries whenever the browser *thinks* it's offline (embedded
            // browsers misreport this), leaving queries stuck in "pending".
            networkMode: "always",
          },
          mutations: {
            networkMode: "always",
          },
        },
      }),
  );

  useEffect(() => {
    if (process.env.NODE_ENV === "development") {
      // Debug handle for driving/inspecting queries from browser tooling.
      (window as unknown as Record<string, unknown>).__queryClient = queryClient;
    }
  }, [queryClient]);

  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          {children}
          <Toaster />
        </AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
