import { describe, it, expect } from "vitest";
import { radiusForConvergence, MIN_RADIUS, MAX_RADIUS } from "@/lib/marker-size";

describe("radiusForConvergence", () => {
  it("floors at MIN_RADIUS for zero convergence", () => {
    expect(radiusForConvergence(0)).toBe(MIN_RADIUS);
  });

  it("caps at MAX_RADIUS for full convergence", () => {
    expect(radiusForConvergence(100)).toBe(MAX_RADIUS);
  });

  it("clamps out-of-range input instead of producing NaN", () => {
    expect(radiusForConvergence(-20)).toBe(MIN_RADIUS);
    expect(radiusForConvergence(400)).toBe(MAX_RADIUS);
    expect(radiusForConvergence(NaN)).toBe(MIN_RADIUS);
  });

  it("grows monotonically", () => {
    expect(radiusForConvergence(25)).toBeLessThan(radiusForConvergence(50));
    expect(radiusForConvergence(50)).toBeLessThan(radiusForConvergence(75));
  });

  it("scales area, not radius, with convergence", () => {
    // radius ∝ sqrt(x) ⇒ a quarter of the score is half the extra radius
    const quarter = radiusForConvergence(25) - MIN_RADIUS;
    const full = radiusForConvergence(100) - MIN_RADIUS;
    expect(quarter).toBeCloseTo(full / 2, 5);
  });
});
