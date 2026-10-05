"use client";

import { useQuery } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import Link from "next/link";

import { apiRequest } from "@/lib/api-client";
import { OPEN_ALERTS_KEY } from "@/lib/monitoring";
import { cn } from "@/lib/utils";

/** Open monitoring alerts on the servers you can use, from any page. */
export function AlertsBell() {
  const count = useQuery({
    queryKey: OPEN_ALERTS_KEY,
    queryFn: () => apiRequest<{ open: number; critical: number }>("/monitoring/alerts/open-count"),
    refetchInterval: 60_000,
    retry: false,
  });
  const open = count.data?.open ?? 0;
  const critical = count.data?.critical ?? 0;
  const label = open
    ? `${open}${open >= 100 ? "+" : ""} open alert${open === 1 ? "" : "s"}${critical ? `, ${critical} critical` : ""}`
    : "Alerts";

  return (
    <Link
      href="/alerts"
      aria-label={label}
      title={label}
      className="relative rounded-lg p-2 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <Bell className="size-4" aria-hidden />
      {open ? (
        <span
          className={cn(
            "absolute right-0.5 top-0.5 min-w-4 rounded-full px-1 text-center text-[10px] font-semibold leading-4",
            critical ? "bg-destructive text-white" : "bg-primary text-primary-foreground",
          )}
          aria-hidden
        >
          {open > 99 ? "99+" : open}
        </span>
      ) : null}
    </Link>
  );
}
