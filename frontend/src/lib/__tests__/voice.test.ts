/**
 * Voice: the parts that are easy to get wrong silently.
 *
 * `speakableText` carries most of the risk. The assistant writes
 * Markdown, and a speech synthesiser reads it literally — so without
 * this, a user dictating a question hears "star star Revenue star star"
 * and every pipe of a variance table read as punctuation.
 */

import { describe, expect, it } from "vitest";

import { nextSpeakableChunk, speakableText } from "../voice";

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

describe("nextSpeakableChunk — following a stream", () => {
  it("returns nothing until a sentence is complete", () => {
    // Speaking a half-sentence forces a pause mid-clause, which sounds
    // worse than waiting a moment.
    expect(nextSpeakableChunk("Revenue fell in", 0)).toBeNull();
  });

  it("returns the first sentence as soon as it lands", () => {
    const chunk = nextSpeakableChunk("Revenue fell in EMEA. It was FX", 0);

    expect(chunk?.text).toBe("Revenue fell in EMEA.");
  });

  it("never re-speaks what it already spoke", () => {
    const text = "One. Two. Three.";
    const first = nextSpeakableChunk(text, 0);
    const second = nextSpeakableChunk(text, first!.consumedTo);

    expect(first!.text).toBe("One. Two. Three.");
    expect(second).toBeNull();
  });

  it("advances the cursor across a growing stream", () => {
    let consumed = 0;
    const spoken: string[] = [];

    for (const snapshot of ["First point.", "First point. Second", "First point. Second point."]) {
      const chunk = nextSpeakableChunk(snapshot, consumed);
      if (chunk) {
        spoken.push(chunk.text);
        consumed = chunk.consumedTo;
      }
    }

    // Trimmed, not " Second point." — each utterance is spoken on its
    // own, so leading whitespace from the join is noise.
    expect(spoken).toEqual(["First point.", "Second point."]);
  });

  it("holds everything back while a code fence is open", () => {
    // Mid-fence text would be spoken as prose before the stripper could
    // see the closing marks and skip it.
    expect(nextSpeakableChunk("Use this. ```\nCellPutN(0);", 0)).toBeNull();
  });

  it("resumes once the fence closes", () => {
    const chunk = nextSpeakableChunk("Use this. ```\nCellPutN(0);\n``` Done.", 0);

    expect(chunk).not.toBeNull();
    expect(chunk!.text).not.toContain("CellPutN");
  });

  it("strips markdown from each sentence it emits", () => {
    expect(nextSpeakableChunk("The **EMEA** variance grew. More", 0)?.text).toBe(
      "The EMEA variance grew.",
    );
  });

  it("consumes a markup-only slice rather than re-examining it forever", () => {
    // A table row yields no speech but must still advance the cursor,
    // or the loop would never reach the prose after it.
    const chunk = nextSpeakableChunk("| a | b |\n\nReal sentence.", 0);

    expect(chunk?.consumedTo).toBeGreaterThan(0);
  });
});

describe("how much sooner speech starts", () => {
  /** Deltas that must arrive before any audio can begin. */
  function deltasBeforeFirstAudio(deltas: string[], streaming: boolean): number {
    if (!streaming) return deltas.length; // old behaviour: wait for `done`

    let text = "";
    for (let i = 0; i < deltas.length; i += 1) {
      text += deltas[i];
      if (nextSpeakableChunk(text, 0)) return i + 1;
    }
    return deltas.length;
  }

  it("starts on the first sentence instead of the last", () => {
    // A realistic tool-using answer: the first sentence is ready long
    // before the model finishes.
    const deltas = [
      "Revenue fell 4% in EMEA.",
      " The driver was currency,",
      " not volume.",
      " Pricing held flat across",
      " all three regions.",
      " I checked the variance cube",
      " and the rate table.",
    ];

    const before = deltasBeforeFirstAudio(deltas, false);
    const after = deltasBeforeFirstAudio(deltas, true);

    expect(before).toBe(7);
    expect(after).toBe(1);
    // Audio now begins after 1/7th of the stream rather than all of it.
    expect(after).toBeLessThan(before);
  });
});
