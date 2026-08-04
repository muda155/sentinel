import { describe, expect, it } from "vitest";
import { confBreakdown, convergenceBreakdown } from "@/lib/score-breakdown";
import type { Hotspot } from "@/lib/api";

const base: Hotspot = {
  hotspot_id: 1, lat: 0, lon: 0,
  conf_score: 0, convergence_score: 0,
  alert_level: "Medium", event_count: 0,
  name: null, start_window: null, end_window: null, created_at: null,
};

describe("confBreakdown", () => {
  it("splits conf_score into its two weighted contributions", () => {
    // 0.7*0.8 + 0.3*0.5 = 0.71 -> 71
    const b = confBreakdown({ ...base, source_density: 0.8, geopolitical_diversity: 0.5, conf_score: 71 });
    expect(b.mode).toBe("weighted");
    expect(b.density).toBeCloseTo(56, 5);
    expect(b.diversity).toBeCloseTo(15, 5);
    expect(b.density + b.diversity).toBeCloseTo(71, 5);
  });

  it("falls back to raw inputs when the default weights do not reproduce the score", () => {
    // The server weights are env-overridable (SENTINEL_CONF_W_DENSITY). If an
    // operator changed them, a bar drawn with 0.7/0.3 would not add up to the
    // number printed above it — so we stop claiming a split.
    const b = confBreakdown({ ...base, source_density: 0.8, geopolitical_diversity: 0.5, conf_score: 40 });
    expect(b.mode).toBe("raw");
  });

  it("reports unavailable when the hotspot has never been scored", () => {
    expect(confBreakdown({ ...base, source_density: null, geopolitical_diversity: null }).mode)
      .toBe("unavailable");
    expect(confBreakdown(base).mode).toBe("unavailable");
  });

  it("treats a genuine zero as scored, not as missing", () => {
    const b = confBreakdown({ ...base, source_density: 0, geopolitical_diversity: 0, conf_score: 0 });
    expect(b.mode).toBe("weighted");
    expect(b.density).toBe(0);
  });
});

describe("convergenceBreakdown", () => {
  it("splits the World Monitor formula into type score and count boost", () => {
    // 3 types * 25 = 75; min(25, 6*2) = 12; total 87
    const b = convergenceBreakdown({ ...base, convergence_types: 3, convergence_events: 6, convergence_score: 87 });
    expect(b.mode).toBe("split");
    expect(b.typeScore).toBe(75);
    expect(b.countBoost).toBe(12);
  });

  it("caps the count boost at 25", () => {
    const b = convergenceBreakdown({ ...base, convergence_types: 1, convergence_events: 400, convergence_score: 50 });
    expect(b.countBoost).toBe(25);
  });

  it("marks the split as clamped when the parts exceed 100", () => {
    // 4 types * 25 = 100, plus a boost -> the server clamps to 100, so the
    // drawn segments must be scaled or the bar overflows its own track.
    const b = convergenceBreakdown({ ...base, convergence_types: 4, convergence_events: 20, convergence_score: 100 });
    expect(b.clamped).toBe(true);
    expect(b.typeScore + b.countBoost).toBeGreaterThan(100);
  });

  it("falls back when the inputs do not reconstruct the published score", () => {
    const b = convergenceBreakdown({ ...base, convergence_types: 1, convergence_events: 1, convergence_score: 90 });
    expect(b.mode).toBe("raw");
  });

  it("reports unavailable when the inputs are absent", () => {
    expect(convergenceBreakdown({ ...base, convergence_score: 50 }).mode).toBe("unavailable");
  });
});
