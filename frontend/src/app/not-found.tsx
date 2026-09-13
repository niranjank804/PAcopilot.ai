import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Shown for unknown routes, and for any resource the API reports as 404.
 *
 * Cross-organization access deliberately returns 404 rather than 403, so
 * this page is also what a user sees when they follow a link to a record
 * belonging to another organization. The wording therefore avoids
 * asserting that the thing does not exist — only that it is not
 * available to them.
 */
export default function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-8 text-center">
      <h2 className="text-xl font-semibold">Page not found</h2>

      <p className="max-w-md text-sm text-muted-foreground">
        This page does not exist, or is not available to your account.
      </p>

      <Link href="/dashboard" className={cn(buttonVariants())}>
        Back to dashboard
      </Link>
    </div>
  );
}
