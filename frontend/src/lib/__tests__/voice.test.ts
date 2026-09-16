/**
 * Voice: the parts that are easy to get wrong silently.
 *
 * `speakableText` carries most of the risk. The assistant writes
 * Markdown, and a speech synthesiser reads it literally — so without
 * this, a user dictating a question hears "star star Revenue star star"
 * and every pipe of a variance table read as punctuation.
 */

import { describe, expect, it } from "vitest";

import { speakableText } from "../voice";

describe("speakableText", () => {
  it("does not read emphasis markers aloud", () => {
    const spoken = speakableText("Revenue fell in **EMEA** and _APAC_.");

    expect(spoken).toBe("Revenue fell in EMEA and APAC.");
    expect(spoken).not.toContain("*");
    expect(spoken).not.toContain("_");
  });

  it("announces a code block instead of reciting it", () => {
    // Reading TurboIntegrator aloud produces noise, and the code is on
    // screen anyway.
    const spoken = speakableText(
      "Use this:\n\n```\nCellPutN(0, 'Sales', 'Jan');\n```\n\nThen run it.",
    );

    expect(spoken).toContain("Code block shown on screen");
    expect(spoken).not.toContain("CellPutN");
    expect(spoken).not.toContain("```");
  });

  it("keeps inline code readable without the backticks", () => {
    expect(speakableText("Call `RunProcess` first.")).toBe(
      "Call RunProcess first.",
    );
  });

  it("reads a link's text, not its URL", () => {
    expect(
      speakableText("See [the standard](https://example.com/very/long/path)."),
    ).toBe("See the standard.");
  });

  it("handles an image without leaving a stray exclamation mark", () => {
    // `![alt](url)` must be matched before the link rule, or the "!"
    // survives and is read as punctuation.
    expect(speakableText("![variance chart](chart.png)")).toBe(
      "variance chart",
    );
  });

  it("strips heading hashes", () => {
    expect(speakableText("## Q3 summary")).toBe("Q3 summary");
  });

  it("reads list items as sentences rather than bullets", () => {
    const spoken = speakableText("- First point\n- Second point");

    expect(spoken).not.toContain("-");
    expect(spoken).toContain("First point");
    expect(spoken).toContain("Second point");
  });

  it("does not read table pipes as punctuation", () => {
    const spoken = speakableText(
      "| Region | Variance |\n| --- | --- |\n| EMEA | -1.2m |",
    );

    expect(spoken).not.toContain("|");
    expect(spoken).toContain("EMEA");
  });

  it("drops horizontal rules", () => {
    expect(speakableText("Before\n\n---\n\nAfter")).not.toContain("---");
  });

  it("collapses blank lines into sentence breaks", () => {
    // Otherwise the synthesiser runs two paragraphs together with no
    // pause and the answer is hard to follow.
    expect(speakableText("First para.\n\nSecond para.")).toBe(
      "First para.. Second para.",
    );
  });

  it("returns empty for content that is only markup", () => {
    // The hook checks for this and stays silent rather than speaking
    // nothing with a "speaking" indicator showing.
    expect(speakableText("---")).toBe("");
    expect(speakableText("   ")).toBe("");
  });

  it("leaves ordinary prose untouched", () => {
    const prose =
      "The EMEA shortfall was driven by currency movement, not volume.";

    expect(speakableText(prose)).toBe(prose);
  });
});
