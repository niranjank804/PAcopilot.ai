/**
 * The builder's controls: the views that render as HTML (KPI cards,
 * matrix, heatmap) are asserted directly; SVG charts need a real layout
 * engine and are covered by the pivot tests underneath them.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "light" }) }));

import { ChartBuilder, download } from "../chart-builder";
import type { VisualizeTable } from "@/lib/visualize";

const TABLE: VisualizeTable = {
  dimensions: ["Period", "Version", "Region"],
  rows: [
    { members: { Period: "Jan", Version: "Actual", Region: "North" }, value: 10 },
    { members: { Period: "Jan", Version: "Actual", Region: "South" }, value: 5 },
    { members: { Period: "Jan", Version: "Budget", Region: "North" }, value: 12 },
    { members: { Period: "Feb", Version: "Actual", Region: "North" }, value: 20 },
  ],
  truncated: false,
};

async function choose(label: string, option: string) {
  await userEvent.click(screen.getByRole("combobox", { name: label }));
  await userEvent.click(await screen.findByRole("option", { name: option }));
}

describe("ChartBuilder", () => {
  it("offers a slicer for every dimension off the axis and legend", () => {
    render(<ChartBuilder table={TABLE} title="Sales" />);

    expect(screen.getByRole("combobox", { name: "Axis" })).toHaveTextContent("Period");
    expect(screen.getByRole("combobox", { name: "Legend" })).toHaveTextContent("Version");
    expect(screen.getByRole("combobox", { name: "Slicer: Region" })).toHaveTextContent("All (summed)");
    expect(screen.getByText(/Summed across Region/)).toBeInTheDocument();
  });

  it("shows a matrix with row and column totals", async () => {
    render(<ChartBuilder table={TABLE} title="Sales" />);

    await choose("Visual", "Matrix");

    const table = screen.getByRole("table");
    const jan = within(table).getByText("Jan").closest("tr")!;
    expect(jan).toHaveTextContent("15");
    expect(jan).toHaveTextContent("12");
    expect(jan).toHaveTextContent("27");
  });

  it("slices to one member", async () => {
    render(<ChartBuilder table={TABLE} title="Sales" />);

    await choose("Visual", "Matrix");
    await choose("Slicer: Region", "South");

    const jan = within(screen.getByRole("table")).getByText("Jan").closest("tr")!;
    expect(jan).toHaveTextContent("5");
    expect(screen.queryByText(/Summed across Region/)).toBeNull();
  });

  it("shows headline numbers as KPI cards", async () => {
    render(<ChartBuilder table={TABLE} title="Sales" />);

    await choose("Visual", "KPI cards");

    expect(screen.getByText("Total")).toBeInTheDocument();
    expect(screen.getByText("47")).toBeInTheDocument();
    expect(screen.getByText("Highest")).toBeInTheDocument();
  });

  it("explains that a heatmap needs a legend dimension", async () => {
    render(<ChartBuilder table={TABLE} title="Sales" />);

    await choose("Legend", "None");
    await choose("Visual", "Heatmap");

    expect(screen.getByText(/needs two dimensions/)).toBeInTheDocument();
  });
});

describe("download", () => {
  it("saves a CSV under its .csv name, as UTF-8 with a byte-order mark", async () => {
    const created: Blob[] = [];
    vi.spyOn(URL, "createObjectURL").mockImplementation((blob) => {
      created.push(blob as Blob);
      return "blob:test";
    });
    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    let saved: { name: string; attached: boolean } | null = null;
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      saved = { name: this.download, attached: document.body.contains(this) };
    });

    download("Workforce.csv", "Period,Value\nQ4 2026,4\n", "text/csv");

    expect(saved).toEqual({ name: "Workforce.csv", attached: true });
    expect(created[0].type).toBe("text/csv;charset=utf-8");
    const bytes = new Uint8Array(await created[0].arrayBuffer());
    expect(Array.from(bytes.slice(0, 3))).toEqual([0xef, 0xbb, 0xbf]);
    // Kept alive while the browser takes the file.
    expect(revoke).not.toHaveBeenCalled();
    vi.restoreAllMocks();
  });
});
