"use client";

import { HelpCircle } from "lucide-react";
import { usePathname } from "next/navigation";

import { ProductTour } from "@/components/product-tour";
import { Button } from "@/components/ui/button";
import { FEATURE_TOURS, useTour } from "@/lib/tour";

/**
 * "Take a tour" for the page you are on.
 *
 * Route-driven rather than configured per page: each screen renders
 * this one component and the steps come from `FEATURE_TOURS`, so adding
 * a tour is a data change and a page can never end up with a button
 * that runs somebody else's steps.
 *
 * Renders nothing where no tour is defined, which is why it is safe to
 * drop into a shared header without auditing every route first.
 *
 * It reuses the global tour's engine and overlay unchanged. A second
 * implementation would be a second thing to keep working on mobile,
 * and the two would drift.
 */
export function FeatureTourButton() {
  const pathname = usePathname();
  const steps = FEATURE_TOURS[pathname];
  const tour = useTour(steps ?? []);

  if (!steps?.length) return null;

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        onClick={tour.start}
        aria-label="Take a tour of this page"
      >
        <HelpCircle className="mr-1.5 h-4 w-4" />
        Take a tour
      </Button>

      {tour.isRunning && tour.step ? (
        <ProductTour
          step={tour.step}
          spotlight={tour.spotlight}
          index={tour.index ?? 0}
          total={tour.steps.length}
          onNext={tour.next}
          onBack={tour.back}
          onSkip={tour.stop}
          // A feature tour is help, not onboarding: finishing one says
          // nothing about whether the user has been introduced to the
          // product, so it deliberately writes no onboarding state.
          onFinish={tour.stop}
        />
      ) : null}
    </>
  );
}
