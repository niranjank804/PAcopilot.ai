/**
 * A cell write as the approver sees it: each cell, its value now and the
 * new one, the changed ones marked.
 */

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CellWriteTable } from "../cell-write-table";

describe("CellWriteTable", () => {
  it("shows each cell's current and new value and marks the ones that change", () => {
    render(
      <CellWriteTable
        reason="New FX rates"
        current={[
          { coordinates: ["Budget", "North", "Rate"], value: 1.1 },
          { coordinates: ["Budget", "South", "Rate"], value: 1.2 },
        ]}
        proposed={[
          { coordinates: ["Budget", "North", "Rate"], value: 1.5 },
          { coordinates: ["Budget", "South", "Rate"], value: 1.2 },
        ]}
      />,
    );

    expect(screen.getByText("Reason: New FX rates")).toBeInTheDocument();
    const north = screen.getByText("Budget · North · Rate").closest("tr")!;
    expect(within(north).getByText("1.1")).toBeInTheDocument();
    expect(within(north).getByText("1.5")).toHaveClass("font-semibold");
    const south = screen.getByText("Budget · South · Rate").closest("tr")!;
    expect(within(south).getByText("(unchanged)")).toBeInTheDocument();
  });
});
