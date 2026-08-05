import { describe, expect, it } from "vitest";
import { confBreakdown, consistencyMix, convergenceBreakdown, sourceMix } from "@/lib/score-breakdown";
import type { Claim, Hotspot, HotspotEvent } from "@/lib/api";

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

  it("treats a zero-input hotspot as not scored, not an empty split", () => {
    // types=0, events=0, score=0 must not fall into split (an empty track) —
    // zero inputs are indistinguishable from "never scored".
    expect(convergenceBreakdown({ ...base, convergence_types: 0, convergence_events: 0, convergence_score: 0 }).mode)
      .toBe("unavailable");
  });

  it("reports unavailable when convergence_score is null (never scored)", () => {
    // A NULL score means the hotspot never went through grid-cell convergence.
    // Coalescing it to 0 would render a hollow split bar under "0.0".
    expect(convergenceBreakdown({ ...base, convergence_types: 3, convergence_events: 6, convergence_score: null }).mode)
      .toBe("unavailable");
  });
});

const claim = (claim_id: number, status: Claim["status"]): Claim =>
  ({ claim_id, claim_text: "x", status, evidence: [] });

describe("consistencyMix", () => {
  it("counts by status with disputed first", () => {
    const mix = consistencyMix([
      claim(1, "corroborated"), claim(2, "disputed"), claim(3, "corroborated"),
    ]);
    expect(mix).toEqual([
      { label: "disputed", count: 1 },
      { label: "corroborated", count: 2 },
    ]);
  });

  it("drops empty buckets so the legend has no zero rows", () => {
    expect(consistencyMix([claim(1, "disputed")])).toEqual([{ label: "disputed", count: 1 }]);
  });

  it("returns nothing for no claims", () => {
    expect(consistencyMix([])).toEqual([]);
  });
});

const ev = (over: Partial<HotspotEvent>): HotspotEvent => ({
  event_id: 1, title: null, url: null, domain: "a.com",
  source_system: "GDELT", event_type_label: "military_conflict",
  event_date: "2026-08-01T00:00:00Z",
  goldstein_scale: null, avg_tone: null, num_sources: null, fatalities: null,
  duplicate_count: 1, trust_tier: 2, trust_score: 0.8, citation_index: 1,
  country_code: "US", ...over,
});

describe("sourceMix", () => {
  it("counts unique domains, not events", () => {
    // scoring.py sums trust over UNIQUE DOMAINS; counting events would let one
    // prolific outlet dominate a chart that claims to explain source_density.
    const mix = sourceMix([
      ev({ event_id: 1, domain: "a.com", trust_tier: 1, country_code: "US" }),
      ev({ event_id: 2, domain: "a.com", trust_tier: 1, country_code: "US" }),
      ev({ event_id: 3, domain: "b.com", trust_tier: 3, country_code: "FR" }),
    ]);
    expect(mix.uniqueDomains).toBe(2);
    expect(mix.tiers).toEqual([{ label: "1", count: 1 }, { label: "3", count: 1 }]);
  });

  it("sorts countries by frequency then alphabetically", () => {
    const mix = sourceMix([
      ev({ event_id: 1, domain: "a.com", country_code: "FR" }),
      ev({ event_id: 2, domain: "b.com", country_code: "US" }),
      ev({ event_id: 3, domain: "c.com", country_code: "US" }),
    ]);
    expect(mix.countries.map((c) => c.label)).toEqual(["US", "FR"]);
  });

  it("buckets a null trust_tier as the lowest tier and a null country as ??", () => {
    const mix = sourceMix([ev({ domain: "z.com", trust_tier: null, country_code: null })]);
    expect(mix.tiers).toEqual([{ label: "4", count: 1 }]);
    expect(mix.countries).toEqual([{ label: "??", count: 1 }]);
  });

  it("returns empty structures for no events", () => {
    expect(sourceMix([])).toEqual({ tiers: [], countries: [], uniqueDomains: 0 });
  });
});
