/**
 * Waking the backend early, and saying so only when it is slow.
 */

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("warmBackend", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("pings /health once per page load, however many pages ask", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null));
    vi.stubGlobal("fetch", fetchMock);

    const { warmBackend } = await import("../backend-warmup");
    warmBackend();
    warmBackend();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/health$/);
  });

  it("swallows a failure, because a sleeping backend is the expected case", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));

    const { warmBackend } = await import("../backend-warmup");

    expect(() => warmBackend()).not.toThrow();
  });
});

describe("useSlowFlag", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("stays quiet for a fast sign-in", async () => {
    const { useSlowFlag } = await import("../backend-warmup");
    const { result, rerender } = renderHook(
      ({ active }) => useSlowFlag(active, 4000),
      { initialProps: { active: true } },
    );

    act(() => vi.advanceTimersByTime(800));
    rerender({ active: false });

    expect(result.current).toBe(false);
  });

  it("speaks up once the wait is long, and resets for the next attempt", async () => {
    const { useSlowFlag } = await import("../backend-warmup");
    const { result, rerender } = renderHook(
      ({ active }) => useSlowFlag(active, 4000),
      { initialProps: { active: true } },
    );

    act(() => vi.advanceTimersByTime(4000));
    expect(result.current).toBe(true);

    rerender({ active: false });
    expect(result.current).toBe(false);

    // A second attempt must not inherit the first one's notice.
    rerender({ active: true });
    expect(result.current).toBe(false);
  });
});
