import { describe, expect, it } from "vitest";

import { workThisPbiPrompt } from "../team";

describe("workThisPbiPrompt", () => {
  it("names the PBI, its view prefix, and keeps every TM1 change a draft", () => {
    const prompt = workThisPbiPrompt("PBI 4076293");

    expect(prompt).toContain("Work PBI 4076293 with me");
    expect(prompt).toContain("'PBI 4076293 - 1 ...'");
    expect(prompt).toContain("clarification email");
    expect(prompt).toMatch(/nothing is sent/i);
    expect(prompt).toMatch(/never say something was run or verified unless you read it back/);
  });
});
