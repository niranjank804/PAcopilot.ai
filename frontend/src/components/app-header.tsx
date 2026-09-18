"use client";

import { HelpCircle, LogOut, Menu, PlayCircle } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { NAV_DESTINATIONS, SidebarBrand, SidebarNav } from "@/components/app-sidebar";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ThemeToggle } from "@/components/theme-toggle";
import { FeatureTourButton } from "@/components/feature-tour-button";
import { useRestartTour } from "@/components/onboarding";
import { useAuth } from "@/lib/auth-context";

function initialsFor(firstName: string, lastName: string): string {
  return `${firstName.charAt(0)}${lastName.charAt(0)}`.toUpperCase();
}

/** The longest nav route that the current path sits under. */
function currentSection(pathname: string): string | null {
  const match = NAV_DESTINATIONS.filter(
    (item) => pathname === item.href || pathname.startsWith(`${item.href}/`),
  ).sort((a, b) => b.href.length - a.href.length)[0];

  return match?.label ?? null;
}

/**
 * The sidebar, for screens too narrow to hold one.
 *
 * Self-contained rather than lifted into the layout: the shell is
 * rendered by a server-protected layout whose only job is auth, and
 * keeping the open/closed state here means the navigation can be
 * restyled without touching route protection.
 */
function MobileNav() {
  const [open, setOpen] = useState(false);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        aria-label="Open navigation"
        className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:hidden"
      >
        <Menu className="size-4" aria-hidden />
      </DialogTrigger>
      <DialogContent className="left-0 top-0 h-full w-72 max-w-[85vw] translate-x-0 translate-y-0 rounded-none border-r border-border p-0 sm:rounded-none">
        <DialogTitle className="sr-only">Navigation</DialogTitle>
        <div className="flex h-full flex-col">
          <SidebarBrand />
          <SidebarNav onNavigate={() => setOpen(false)} />
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function AppHeader() {
  const { user, logout } = useAuth();
  const restartTour = useRestartTour();
  const router = useRouter();
  const pathname = usePathname();
  const section = currentSection(pathname ?? "");

  const handleLogout = () => {
    logout();
    router.push("/login");
  };

  // Solid, not translucent-with-blur: backdrop-filter turns the element
  // into the positioning root for any fixed descendant, and the page tour
  // is rendered from the button below.
  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-background px-4 md:px-6">
      <div className="flex min-w-0 items-center gap-2">
        <MobileNav />
        {/* Says where you are, which the sidebar cannot do once it is a
            drawer. */}
        {section ? (
          <span className="truncate text-sm font-medium text-foreground">
            {section}
          </span>
        ) : null}
      </div>

      <div className="flex items-center gap-1">
        <span className="mr-2 hidden text-sm text-muted-foreground lg:inline">
          {user ? `${user.first_name} ${user.last_name}` : ""}
        </span>
        {/* Page-specific help, where a tour exists for the current
            route. Renders nothing elsewhere, so it needs no per-page
            wiring. */}
        <FeatureTourButton />
        {/* Help. Also the last stop on the product tour, which is how
            someone learns the tour can be replayed from here. */}
        <DropdownMenu>
          <DropdownMenuTrigger
            data-tour="help-menu"
            aria-label="Help"
            className="rounded-lg p-2 text-muted-foreground outline-none transition-colors hover:bg-secondary hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          >
            <HelpCircle className="size-4" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuGroup>
              <DropdownMenuLabel>Help</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() => restartTour.mutate()}
                disabled={restartTour.isPending}
              >
                <PlayCircle className="mr-2 h-4 w-4" />
                Take product tour
              </DropdownMenuItem>
              {/* No Documentation entry: there is no user-facing
                  documentation site yet, and pointing this at a
                  repository README would be a link that looks like help
                  and is not. It belongs here the day docs exist. */}
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
        <ThemeToggle />
        <DropdownMenu>
          <DropdownMenuTrigger className="ml-1 rounded-full outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background">
            <Avatar className="size-8">
              <AvatarFallback className="text-xs">
                {user ? initialsFor(user.first_name, user.last_name) : "?"}
              </AvatarFallback>
            </Avatar>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuGroup>
              <DropdownMenuLabel>{user?.username}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={handleLogout}>
                <LogOut className="mr-2 h-4 w-4" />
                Log out
              </DropdownMenuItem>
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
