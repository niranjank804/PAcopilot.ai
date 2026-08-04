/**
 * Route protection and the app shell.
 *
 * Two behaviours worth pinning: an unauthenticated visitor must never see
 * a navigable app, and an authenticated one must not have the shell
 * blanked while auth resolves — the latter was a real regression that
 * flashed the whole page on every hard load.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => "/dashboard",
}));

const useAuth = vi.fn();
vi.mock("@/lib/auth-context", () => ({ useAuth: () => useAuth() }));

vi.mock("@/components/app-sidebar", () => ({
  AppSidebar: () => <nav data-testid="sidebar">nav</nav>,
}));
vi.mock("@/components/app-header", () => ({
  AppHeader: () => <header data-testid="header">header</header>,
}));

import AppLayout from "../layout";

beforeEach(() => {
  replace.mockClear();
});

describe("while authentication is resolving", () => {
  beforeEach(() => {
    useAuth.mockReturnValue({ isAuthenticated: false, isLoading: true });
  });

  it("keeps the shell on screen", () => {
    render(<AppLayout>content</AppLayout>);

    // Blanking these was what produced the full-page flash on hard load.
    expect(screen.getByTestId("sidebar")).toBeInTheDocument();
    expect(screen.getByTestId("header")).toBeInTheDocument();
  });

  it("does not redirect before the answer is known", () => {
    render(<AppLayout>content</AppLayout>);

    expect(replace).not.toHaveBeenCalled();
  });

  it("shows a busy region instead of the page body", () => {
    render(<AppLayout>secret content</AppLayout>);

    expect(screen.queryByText("secret content")).not.toBeInTheDocument();
    expect(document.querySelector('[aria-busy="true"]')).toBeInTheDocument();
  });
});

describe("when signed out", () => {
  beforeEach(() => {
    useAuth.mockReturnValue({ isAuthenticated: false, isLoading: false });
  });

  it("renders nothing at all", () => {
    const { container } = render(<AppLayout>secret content</AppLayout>);

    // Not merely hidden: an unauthenticated visitor must never receive a
    // navigable app, even for the moment before the redirect lands.
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByTestId("sidebar")).not.toBeInTheDocument();
  });

  it("redirects to the login page", () => {
    render(<AppLayout>content</AppLayout>);

    expect(replace).toHaveBeenCalledWith("/login");
  });
});

describe("when signed in", () => {
  beforeEach(() => {
    useAuth.mockReturnValue({ isAuthenticated: true, isLoading: false });
  });

  it("renders the shell and the page", () => {
    render(<AppLayout>page content</AppLayout>);

    expect(screen.getByTestId("sidebar")).toBeInTheDocument();
    expect(screen.getByText("page content")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });
});
