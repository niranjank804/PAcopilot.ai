/**
 * The lifecycle and the checklist say, in words, what happened to a change
 * and what was checked — never colour alone.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChangeChecks, ChangeLifecycle } from "../change-lifecycle";

describe("ChangeLifecycle", () => {
  it("writes each step's state out", () => {
    render(
      <ChangeLifecycle
        steps={[
          { key: "validated", label: "Validated", state: "done", at: null, detail: null },
          { key: "approval", label: "Approval", state: "current", at: null, detail: "waiting for someone with deploy rights" },
          { key: "deployed", label: "Applied", state: "pending", at: null, detail: null },
        ]}
      />,
    );

    expect(screen.getByText(/— done/)).toBeInTheDocument();
    expect(screen.getByText(/— now/)).toBeInTheDocument();
    expect(screen.getByText(/— to do/)).toBeInTheDocument();
    expect(screen.getByText("waiting for someone with deploy rights")).toBeInTheDocument();
  });
});

describe("ChangeChecks", () => {
  const checks = [
    { name: "Compiled on the server (not saved)", status: "fail" as const, detail: "1 compile error(s)", items: ["Prolog line 2: Syntax error"] },
    { name: "Code review", status: "warn" as const, detail: "1 finding(s)" },
    { name: "Static analysis", status: "pass" as const, detail: "no undeclared names" },
  ];

  it("lists every check with its result and items", () => {
    render(<ChangeChecks checks={checks} />);

    expect(screen.getByText(/Failed: 1 compile error/)).toBeInTheDocument();
    expect(screen.getByText("Prolog line 2: Syntax error")).toBeInTheDocument();
    expect(screen.getByText(/Passed: no undeclared names/)).toBeInTheDocument();
  });

  it("can show only what needs attention", () => {
    render(<ChangeChecks checks={checks} onlyConcerns />);

    expect(screen.queryByText("Static analysis")).not.toBeInTheDocument();
    expect(screen.getByText("Code review")).toBeInTheDocument();
  });
});
