import { describe, it, expect } from "vitest";
import { backoffDelay } from "@/lib/sse";

describe("backoffDelay", () => {
  it("starts near 1s on attempt 0", () => {
    const d = backoffDelay(0, () => 0.5);   // jitter rng -> 0 offset
    expect(d).toBe(1000);
  });
  it("doubles per attempt", () => {
    expect(backoffDelay(1, () => 0.5)).toBe(2000);
    expect(backoffDelay(2, () => 0.5)).toBe(4000);
  });
  it("caps at 30s", () => {
    expect(backoffDelay(20, () => 0.5)).toBe(30000);
  });
  it("applies +/-500ms jitter and never goes negative", () => {
    expect(backoffDelay(0, () => 0)).toBe(500);     // -500 offset
    expect(backoffDelay(0, () => 1)).toBe(1500);    // +500 offset
    expect(backoffDelay(0, () => 0) >= 0).toBe(true);
  });
});
