"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { AppHeader } from "@/components/app-header";
import { AppSidebar } from "@/components/app-sidebar";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth-context";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/login");
    }
  }, [isLoading, isAuthenticated, router]);

  // Resolved, and not signed in — the effect above is redirecting. Rendering
  // the shell here would flash a navigable app at someone on their way to
  // /login.
  if (!isLoading && !isAuthenticated) {
    return null;
  }

  // While auth is still resolving the shell renders as normal. It depends on
  // nothing but the route (AppSidebar) and tolerates a null user
  // (AppHeader), so replacing the whole page with a centred skeleton during
  // the 1-3s bootstrap blanked the sidebar and header on every hard load for
  // no reason. Only the page body waits now.
  return (
    <div className="flex flex-1">
      <AppSidebar />
      <div className="flex flex-1 flex-col">
        <AppHeader />
        <main className="flex-1 overflow-y-auto p-6">
          {isLoading ? (
            <div className="space-y-4" aria-busy="true">
              <Skeleton className="h-8 w-64" />
              <Skeleton className="h-4 w-96" />
              <Skeleton className="h-64 w-full" />
            </div>
          ) : (
            children
          )}
        </main>
      </div>
    </div>
  );
}
