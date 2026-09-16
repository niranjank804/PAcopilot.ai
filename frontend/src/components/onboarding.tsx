"use client";

import { useMutation } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ProductTour } from "@/components/product-tour";
import { Button } from "@/components/ui/button";
import { apiRequest } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import { PRODUCT_TOUR, useTour } from "@/lib/tour";

/**
 * First-login onboarding, and the tour it starts.
 *
 * Whether to offer this is decided by the *server* — `useAuth`'s user
 * carries `onboarding_completed_at` and `onboarding_dismissed_at` — not
 * by a browser flag. Signing in on a second machine should not replay
 * an introduction somebody has already sat through, and clearing site
 * data should not either.
 *
 * "Remind me later" is deliberately not persisted as a third state. It
 * means *this session*: the welcome does not return until the next
 * sign-in, and nothing is written, so the user is offered it again
 * rather than being quietly opted out by a button they pressed to get
 * on with something.
 */

type Action = "completed" | "dismissed" | "restart";

export function Onboarding() {
  const { user, refreshUser } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  const [postponed, setPostponed] = useState(false);
  const tour = useTour(PRODUCT_TOUR);

  const record = useMutation({
    mutationFn: (action: Action) =>
      apiRequest("/users/me/onboarding", {
        method: "POST",
        body: { action },
      }),
    // The user object drives whether the welcome shows, so it has to be
    // re-read or the dialog reappears on the next render. It lives in
    // the auth context's state rather than a query cache, so this is a
    // refetch and not an invalidation.
    onSettled: () => refreshUser(),
  });

  const step = tour.step;

  // Steps can live on different screens. Navigating here — rather than
  // inside the step data — keeps the tour declarative and means a step
  // whose route is already current costs nothing.
  useEffect(() => {
    if (step?.route && pathname !== step.route) {
      router.push(step.route);
    }
  }, [step, pathname, router]);

  const finish = useCallback(() => {
    tour.stop();
    record.mutate("completed");
  }, [tour, record]);

  const skip = useCallback(() => {
    tour.stop();
    // Skipping mid-tour is still a decision about the tour: it should
    // not reappear on every page load afterwards.
    record.mutate("dismissed");
  }, [tour, record]);

  if (!user) return null;

  const hasSeenIt = Boolean(
    user.onboarding_completed_at ?? user.onboarding_dismissed_at,
  );

  if (tour.isRunning && step) {
    return (
      <ProductTour
        step={step}
        spotlight={tour.spotlight}
        index={tour.index ?? 0}
        total={tour.steps.length}
        onNext={tour.next}
        onBack={tour.back}
        onSkip={skip}
        onFinish={finish}
      />
    );
  }

  if (hasSeenIt || postponed) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="welcome-title"
        className="w-full max-w-md rounded-lg border bg-background p-6 shadow-lg"
      >
        <h2 id="welcome-title" className="text-lg font-semibold">
          Welcome to PA-Copilot
        </h2>
        <p className="text-muted-foreground mt-2 text-sm">
          A two-minute tour of your workspace — where to connect Planning
          Analytics, how to ask questions, and how changes get reviewed before
          anything is written to TM1.
        </p>

        <div className="mt-6 flex flex-wrap items-center justify-end gap-2">
          <Button variant="ghost" onClick={() => record.mutate("dismissed")}>
            Skip tour
          </Button>
          <Button variant="outline" onClick={() => setPostponed(true)}>
            Remind me later
          </Button>
          <Button onClick={tour.start} data-tour="start-tour">
            Start tour
          </Button>
        </div>
      </div>
    </div>
  );
}

/**
 * Restarting from Help. Clears the stored state so the tour is offered
 * again, and starts it immediately rather than waiting for a reload.
 */
export function useRestartTour() {
  const { refreshUser } = useAuth();

  return useMutation({
    mutationFn: () =>
      apiRequest("/users/me/onboarding", {
        method: "POST",
        body: { action: "restart" },
      }),
    onSettled: () => refreshUser(),
  });
}
