/**
 * The shared Markdown renderer.
 *
 * QA finding: Knowledge Base answers showed `**bold**` literally while
 * Chat rendered the same model output. Both now go through this one
 * component, so these tests are what hold the two surfaces together.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Markdown } from "../markdown";

describe("Markdown", () => {
  it("renders emphasis as elements, not asterisks", () => {
    // The exact symptom from the report.
    render(<Markdown>{"The variance was **unfavourable** this quarter."}</Markdown>);

    const bold = screen.getByText("unfavourable");

    expect(bold.tagName).toBe("STRONG");
    expect(screen.queryByText(/\*\*/)).not.toBeInTheDocument();
  });

  it("renders lists", () => {
    render(<Markdown>{"- EMEA\n- APAC"}</Markdown>);

    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("renders GFM tables", () => {
    // Financial answers come back as tables more often than prose; without
    // the GFM plugin a table is a run of pipe characters.
    render(
      <Markdown>{"| Region | Var |\n|---|---|\n| EMEA | -1.2m |"}</Markdown>,
    );

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("-1.2m")).toBeInTheDocument();
  });

  it("opens links in a new tab without leaking the opener", () => {
    render(<Markdown>{"See [the pack](https://example.com/pack)."}</Markdown>);

    const link = screen.getByRole("link", { name: "the pack" });

    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
  });

  it("steps headings down so a model's title does not shout", () => {
    render(<Markdown>{"# Summary"}</Markdown>);

    // h1 in the source becomes an h3 in the card.
    expect(screen.getByRole("heading", { level: 3, name: "Summary" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1 })).not.toBeInTheDocument();
  });
});
