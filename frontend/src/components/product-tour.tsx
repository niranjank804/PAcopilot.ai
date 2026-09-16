"use client";

import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import type { Spotlight, TourStep } from "@/lib/tour";
import { cn } from "@/lib/utils";

/**
 * The tour's appearance. Its state lives in `@/lib/tour`.
 *
 * Drawn as four dimming panels around the target rather than one
 * overlay with a cut-out. A cut-out needs either an SVG mask or
 * `clip-path`, and both make the hole swallow clicks — so the thing
 * being pointed at becomes unclickable precisely while it is being
 * explained. Four rectangles leave the middle genuinely untouched.
 */

const GAP = 8;
const POPOVER_WIDTH = 320;

function popoverPosition(spotlight: Spotlight | null) {
  if (typeof window === "undefined") return { top: 0, left: 0 };

  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;

  // No target — centre it and explain in prose instead of pointing.
  if (!spotlight) {
    return {
      top: window.scrollY + viewportHeight / 2 - 80,
      left: Math.max(GAP, viewportWidth / 2 - POPOVER_WIDTH / 2),
    };
  }

  const below = spotlight.top + spotlight.height + GAP;
  const wouldOverflowBottom =
    below + 200 > window.scrollY + viewportHeight && spotlight.top > 220;

  return {
    top: wouldOverflowBottom ? spotlight.top - 200 - GAP : below,
    // Clamped to the viewport so a target near the right edge — or a
    // narrow phone, where the element may be wider than the popover —
    // does not push the card off-screen.
    left: Math.min(
      Math.max(GAP, spotlight.left),
      Math.max(GAP, viewportWidth - POPOVER_WIDTH - GAP),
    ),
  };
}

export function ProductTour({
  step,
  spotlight,
  index,
  total,
  onNext,
  onBack,
  onSkip,
  onFinish,
}: {
  step: TourStep;
  spotlight: Spotlight | null;
  index: number;
  total: number;
  onNext: () => void;
  onBack: () => void;
  onSkip: () => void;
  onFinish: () => void;
}) {
  const isLast = index === total - 1;
  const cardRef = useRef<HTMLDivElement | null>(null);

  // Focus moves to the card on every step so a keyboard or screen
  // reader user is taken along rather than left behind on whatever they
  // last touched.
  useEffect(() => {
    cardRef.current?.focus();
  }, [index]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onSkip();
      if (event.key === "ArrowRight") onNext();
      if (event.key === "ArrowLeft") onBack();
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onNext, onBack, onSkip]);

  const position = popoverPosition(spotlight);

  return (
    <div className="pointer-events-none fixed inset-0 z-[60]">
      {spotlight ? (
        <>
          {/* Four panels, leaving the target itself clickable. */}
          <div
            className="pointer-events-auto absolute bg-black/50"
            style={{ top: 0, left: 0, right: 0, height: spotlight.top }}
            onClick={onSkip}
          />
          <div
            className="pointer-events-auto absolute bg-black/50"
            style={{
              top: spotlight.top + spotlight.height,
              left: 0,
              right: 0,
              bottom: 0,
            }}
            onClick={onSkip}
          />
          <div
            className="pointer-events-auto absolute bg-black/50"
            style={{
              top: spotlight.top,
              left: 0,
              width: spotlight.left,
              height: spotlight.height,
            }}
            onClick={onSkip}
          />
          <div
            className="pointer-events-auto absolute bg-black/50"
            style={{
              top: spotlight.top,
              left: spotlight.left + spotlight.width,
              right: 0,
              height: spotlight.height,
            }}
            onClick={onSkip}
          />
          <div
            aria-hidden
            className="absolute rounded-md ring-2 ring-primary ring-offset-2"
            style={{
              top: spotlight.top,
              left: spotlight.left,
              width: spotlight.width,
              height: spotlight.height,
            }}
          />
        </>
      ) : (
        <div className="pointer-events-auto absolute inset-0 bg-black/50" onClick={onSkip} />
      )}

      <div
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        aria-describedby="tour-body"
        tabIndex={-1}
        className={cn(
          "pointer-events-auto absolute rounded-lg border bg-background p-4 shadow-lg outline-none",
          "focus-visible:ring-2 focus-visible:ring-ring",
        )}
        style={{
          top: position.top,
          left: position.left,
          width: POPOVER_WIDTH,
          maxWidth: "calc(100vw - 16px)",
        }}
      >
        <p className="text-muted-foreground text-xs" aria-hidden>
          Step {index + 1} of {total}
        </p>
        <h2 id="tour-title" className="mt-1 text-sm font-semibold">
          {step.title}
        </h2>
        <p id="tour-body" className="text-muted-foreground mt-2 text-sm">
          {step.body}
        </p>

        <div className="mt-4 flex items-center justify-between gap-2">
          <Button variant="ghost" size="sm" onClick={onSkip}>
            Skip tour
          </Button>
          <div className="flex gap-2">
            {index > 0 ? (
              <Button variant="outline" size="sm" onClick={onBack}>
                Back
              </Button>
            ) : null}
            <Button size="sm" onClick={isLast ? onFinish : onNext}>
              {isLast ? "Finish" : "Next"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
