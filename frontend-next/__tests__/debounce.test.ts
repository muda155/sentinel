import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { trailingDebounce } from "@/lib/debounce";

describe("trailingDebounce", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("collapses a burst into one trailing call", () => {
    const fn = vi.fn();
    const debounced = trailingDebounce(fn, 3000);
    for (let i = 0; i < 10; i++) debounced();
    expect(fn).not.toHaveBeenCalled();
    vi.advanceTimersByTime(3000);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("fires again for calls after the window", () => {
    const fn = vi.fn();
    const debounced = trailingDebounce(fn, 3000);
    debounced();
    vi.advanceTimersByTime(3000);
    debounced();
    vi.advanceTimersByTime(3000);
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("cancel drops the pending call", () => {
    const fn = vi.fn();
    const debounced = trailingDebounce(fn, 3000);
    debounced();
    debounced.cancel();
    vi.advanceTimersByTime(3000);
    expect(fn).not.toHaveBeenCalled();
  });

  it("resets the window on each call within the window", () => {
    const fn = vi.fn();
    const debounced = trailingDebounce(fn, 3000);
    debounced();
    vi.advanceTimersByTime(2000);
    debounced();
    vi.advanceTimersByTime(2000);
    expect(fn).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1000);
    expect(fn).toHaveBeenCalledTimes(1);
  });
});
