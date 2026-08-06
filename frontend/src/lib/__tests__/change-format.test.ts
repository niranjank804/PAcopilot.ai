/**
 * The status label is the product's safety guarantee rendered as two words.
 * It appears on five screens, so it is defined once and tested here.
 */

import { describe, expect, it } from "vitest";

import { STATUS_LABEL, statusLabel } from "@/lib/change-format";
import type { ChangeStatus } from "@/lib/types";

describe("statusLabel", () => {
  it("shows a draft as STET", () => {
    expect(statusLabel("draft")).toBe("STET");
  });

  it("leaves every other status in plain English", () => {
    // Inventing vocabulary for states that already read clearly would be
    // branding at the user's expense.
    expect(statusLabel("executed")).toBe("executed");
    expect(statusLabel("failed")).toBe("failed");
    expect(statusLabel("rolled_back")).toBe("rolled back");
    expect(statusLabel("superseded")).toBe("superseded");
  });

  it("calls a rejected change discarded, matching the button that causes it", () => {
    expect(statusLabel("rejected")).toBe("discarded");
  });

  it("never renders a raw underscore to the user", () => {
    for (const status of Object.keys(STATUS_LABEL) as ChangeStatus[]) {
      expect(statusLabel(status)).not.toContain("_");
    }
  });

  it("falls back readably for a status the frontend does not know", () => {
    // A backend that adds a status must not render a blank badge.
    expect(statusLabel("awaiting_review")).toBe("awaiting review");
  });
});
