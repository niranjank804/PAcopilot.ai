"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { AppHeader } from "@/components/app-header";
import { AppSidebar } from "@/components/app-sidebar";
import { KeepAwake } from "@/components/backend-warmup";
import { Onboarding } from "@/components/onboarding";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth-context";
import { cn } from "@/lib/utils";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  // The assistant is a workspace, not a document: it takes the whole width
  // and less padding, so a long answer or a draft has room.
  const workspace = pathname === "/chat" || pathname.startsWith("/chat/");

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
    <div className="flex h-dvh overflow-hidden">
      <AppSidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <AppHeader />
        <main
          className={cn(
            "mx-auto min-h-0 w-full flex-1 overflow-y-auto px-4",
            workspace ? "max-w-none py-4 md:px-6 md:py-5" : "max-w-[1400px] py-6 md:px-8 md:py-8",
          )}
        >
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

      {/* Mounted in the shell rather than on the dashboard: the tour
          walks across several routes, so it has to outlive any one
          page. It renders nothing once the user has finished or
          dismissed it. */}
      <Onboarding />
      <KeepAwake />
    </div>
  );
}
