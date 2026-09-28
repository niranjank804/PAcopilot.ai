/**
 * The menu folds to icons to give the page its width back, and stays
 * folded on the next visit. Folded, every destination must still be
 * reachable and named — only the visible label goes.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  usePathname: () => "/chat",
}));

import { AppSidebar } from "../app-sidebar";

describe("AppSidebar", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("collapses to named icons and remembers it", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<AppSidebar />);

    expect(screen.getByText("AI Assistant")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Collapse menu" }));

    expect(screen.queryByText("AI Assistant")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "AI Assistant" })).toHaveAttribute("href", "/chat");
    expect(window.localStorage.getItem("pa-copilot-sidebar-collapsed")).toBe("1");

    unmount();
    render(<AppSidebar />);
    expect(await screen.findByRole("button", { name: "Expand menu" })).toBeInTheDocument();
  });
});
