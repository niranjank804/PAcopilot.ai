"use client";

import { Tooltip as TooltipPrimitive } from "@base-ui/react/tooltip";
import type { ReactElement, ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * Hover and focus help for a control.
 *
 * Every control that is not self-explanatory gets one, so a person can
 * rest the cursor on an option and learn what it does — and why — before
 * using it. Opens on keyboard focus too, so the same help reaches people
 * who never hover. The native `title` attribute did this before, with a
 * one-second delay and no styling; this replaces it.
 *
 * `children` must be an element that forwards a ref and spreads props
 * (Button, Link, a plain button): the trigger is attached to it rather
 * than wrapping it, so layout is unchanged.
 */
export function Tip({
  content,
  children,
  side = "top",
  className,
}: {
  content: ReactNode;
  children: ReactElement;
  side?: "top" | "bottom" | "left" | "right";
  className?: string;
}) {
  if (!content) return children;

  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger render={children} />
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Positioner side={side} sideOffset={6} className="z-[70]">
          <TooltipPrimitive.Popup
            // base-ui leaves the role off; assistive technology and the
            // browser tests both look for it.
            role="tooltip"
            className={cn(
              "max-w-72 rounded-lg border border-border bg-popover px-3 py-2 text-[0.8125rem] leading-5 text-popover-foreground shadow-raised",
              "origin-[var(--transform-origin)] transition-[opacity,transform] duration-150",
              "data-[starting-style]:scale-95 data-[starting-style]:opacity-0",
              "data-[ending-style]:scale-95 data-[ending-style]:opacity-0",
              className,
            )}
          >
            {content}
          </TooltipPrimitive.Popup>
        </TooltipPrimitive.Positioner>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

/** Mounted once, near the root: tooltips share one hover delay, so moving
 * between neighbouring controls does not re-wait on each. */
export function TooltipProvider({ children }: { children: ReactNode }) {
  return (
    <TooltipPrimitive.Provider delay={350} closeDelay={80}>
      {children}
    </TooltipPrimitive.Provider>
  );
}
