import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EnvironmentBadge } from "../environment-badge";

describe("EnvironmentBadge", () => {
  it("writes the environment out and explains its rules on hover", () => {
    render(<EnvironmentBadge environment="prod" />);

    const badge = screen.getByText("PROD");
    expect(badge).toHaveAttribute("title", expect.stringContaining("second person"));
  });

  it("treats a connection without an environment as DEV", () => {
    render(<EnvironmentBadge environment={undefined} />);

    expect(screen.getByText("DEV")).toBeInTheDocument();
  });
});
