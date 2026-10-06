/**
 * A new view as the approver sees it: cube, view name and the MDX, and the
 * server's version only when it differs from what was approved.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CHANGE_TYPE_LABEL } from "@/lib/change-format";

import { ViewChange } from "../view-change";

const MDX = "SELECT {[Region].[North]} ON 0 FROM [Sales]";

describe("ViewChange", () => {
  it("shows the cube, the view name and the MDX", () => {
    render(
      <ViewChange cube="Sales" viewName="PBI1234 - 1 Result" mdx={MDX} rationale="Evidence for PBI1234" />,
    );

    expect(screen.getByText("Sales")).toBeInTheDocument();
    expect(screen.getByText("PBI1234 - 1 Result")).toBeInTheDocument();
    expect(screen.getByText(MDX)).toBeInTheDocument();
    expect(screen.getByText("Reason: Evidence for PBI1234")).toBeInTheDocument();
    expect(screen.queryByText(/On the server now/)).not.toBeInTheDocument();
    expect(CHANGE_TYPE_LABEL.create_view).toBe("Create view");
  });

  it("shows the server's MDX only when it differs", () => {
    const { rerender } = render(
      <ViewChange cube="Sales" viewName="V" mdx={MDX} currentMdx={`  ${MDX}\n`} />,
    );
    expect(screen.queryByText(/On the server now/)).not.toBeInTheDocument();

    rerender(<ViewChange cube="Sales" viewName="V" mdx={MDX} currentMdx="SELECT {} ON 0 FROM [Sales]" />);
    expect(screen.getByText(/On the server now/)).toBeInTheDocument();
    expect(screen.getByText("SELECT {} ON 0 FROM [Sales]")).toBeInTheDocument();
  });
});
