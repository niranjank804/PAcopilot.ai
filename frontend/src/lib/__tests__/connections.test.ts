import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ apiRequest: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ apiRequest: mocks.apiRequest }));

import { fetchUsableConnections } from "../connections";

describe("fetchUsableConnections", () => {
  it("leaves out connections the server marks as manage-only", async () => {
    mocks.apiRequest.mockResolvedValue([
      { id: "mine", can_use: true },
      { id: "shared" },
      { id: "members-private", can_use: false },
    ]);

    const usable = await fetchUsableConnections();

    expect(usable.map((c) => c.id)).toEqual(["mine", "shared"]);
  });
});
