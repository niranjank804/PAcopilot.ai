/**
 * An approver sees every value a run will take, and afterwards what TM1
 * reported — not what the assistant hoped.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { TM1ChangeSummary } from "@/lib/types";

import { RunPlan } from "../run-plan";

function change(overrides: Partial<TM1ChangeSummary> = {}): TM1ChangeSummary {
  return {
    id: "c1",
    connection_id: "k1",
    change_type: "run_process",
    target_name: "Load Sales",
    status: "draft",
    new_content: { parameters: { pYear: "2026" } },
    previous_content: null,
    validation_errors: null,
    impact: [
      { kind: "parameter", name: "pYear", value: "2026", source: "given" },
      { kind: "parameter", name: "pMonth", value: "Jan", source: "default" },
      { kind: "writes_cube", name: "Sales" },
    ] as unknown as TM1ChangeSummary["impact"],
    error_message: null,
    superseded_by: null,
    created_by: "u1",
    executed_by: null,
    created_at: "2026-10-03T10:00:00Z",
    executed_at: null,
    rolled_back_at: null,
    execution_result: null,
    ...overrides,
  };
}

describe("RunPlan", () => {
  it("lists every parameter, including the defaults nobody typed, and the cubes written", () => {
    render(<RunPlan change={change()} />);

    expect(screen.getByText("pYear")).toBeInTheDocument();
    expect(screen.getByText("pMonth")).toBeInTheDocument();
    expect(screen.getByText("Jan")).toBeInTheDocument();
    expect(screen.getByText(/Sales/)).toBeInTheDocument();
  });

  it("shows the status TM1 reported after the run", () => {
    render(
      <RunPlan
        change={change({
          status: "failed",
          execution_result: { success: false, status: "Aborted", error_log_file: "TM1ProcessError_x.log" },
        })}
      />,
    );

    expect(screen.getByText(/Aborted/)).toBeInTheDocument();
  });
});
