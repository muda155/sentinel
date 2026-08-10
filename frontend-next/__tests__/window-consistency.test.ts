import { describe, expect, it } from "vitest";
import { consistencyTrusted, windowConsistency } from "@/lib/window-consistency";
import type { Claim, Hotspot, HotspotEvent } from "@/lib/api";

const W = { from: "2026-08-05T00:00:00Z", to: "2026-08-06T00:00:00Z" };

const ev = (id: number, domain: string, trust: number, date: string): HotspotEvent => ({
  event_id: id, title: null, url: null, domain,
  source_system: "GDELT", event_type_label: "military_conflict", event_date: date,
  goldstein_scale: null, avg_tone: null, num_sources: null, fatalities: null,
  duplicate_count: 1, trust_tier: 1, trust_score: trust,
  country_code: "US", citation_index: id,
});

const claim = (o: Partial<Claim>): Claim => ({
  claim_id: 1, claim_text: "Shelling reported downtown.",
  status: "corroborated", origin_domains: [], evidence: [], ...o,
});

const inWindow = "2026-08-05T06:00:00Z";
const outside = "2026-08-09T06:00:00Z";

describe("windowConsistency", () => {
  it("corroborates a claim with two independent supporters in the window", () => {
    const events = [ev(1, "a.com", 0.9, inWindow), ev(2, "b.com", 0.8, inWindow)];
    const c = claim({
      evidence: [
        { event_id: 1, citation_index: 1, relation: "supports", probability: 0.9, domain: "a.com" },
        { event_id: 2, citation_index: 2, relation: "supports", probability: 0.9, domain: "b.com" },
      ],
    });
    const r = windowConsistency([c], events, W);
    expect(r.outcomes[0].status).toBe("corroborated");
    expect(r.mode).toBe("score");
    if (r.mode === "score") expect(r.score).toBeCloseTo(100, 6);
  });

  it("does not let a claim's own source corroborate it", () => {
    const events = [ev(1, "a.com", 0.9, inWindow), ev(2, "b.com", 0.8, inWindow)];
    const c = claim({
      origin_domains: ["a.com"],
      evidence: [
        { event_id: 1, citation_index: 1, relation: "supports", probability: 0.9, domain: "a.com" },
        { event_id: 2, citation_index: 2, relation: "supports", probability: 0.9, domain: "b.com" },
      ],
    });
    // One eligible supporter left, so it cannot reach corroborated.
    expect(windowConsistency([c], events, W).outcomes[0].status).toBe("uncorroborated");
  });

  it("marks a claim unverifiable when origin_domains predates migration 023", () => {
    const events = [ev(1, "a.com", 0.9, inWindow)];
    const c = claim({
      origin_domains: null,
      evidence: [{ event_id: 1, citation_index: 1, relation: "supports", probability: 0.9, domain: "a.com" }],
    });
    const r = windowConsistency([c], events, W);
    expect(r.outcomes[0].status).toBe("unverifiable");
    expect(r.mode).toBe("countsOnly");
  });

  it("disputes a claim when contradiction reaches the ratio", () => {
    const events = [ev(1, "a.com", 0.9, inWindow), ev(2, "b.com", 0.9, inWindow)];
    const c = claim({
      evidence: [
        { event_id: 1, citation_index: 1, relation: "supports", probability: 0.9, domain: "a.com" },
        { event_id: 2, citation_index: 2, relation: "contradicts", probability: 0.9, domain: "b.com" },
      ],
    });
    expect(windowConsistency([c], events, W).outcomes[0].status).toBe("disputed");
  });

  it("ignores evidence whose event falls outside the window", () => {
    const events = [ev(1, "a.com", 0.9, inWindow), ev(2, "b.com", 0.8, outside)];
    const c = claim({
      evidence: [
        { event_id: 1, citation_index: 1, relation: "supports", probability: 0.9, domain: "a.com" },
        { event_id: 2, citation_index: 2, relation: "supports", probability: 0.9, domain: "b.com" },
      ],
    });
    expect(windowConsistency([c], events, W).outcomes[0].status).toBe("uncorroborated");
  });

  it("ignores judgments below the NLI probability floor", () => {
    const events = [ev(1, "a.com", 0.9, inWindow), ev(2, "b.com", 0.8, inWindow)];
    const c = claim({
      evidence: [
        { event_id: 1, citation_index: 1, relation: "supports", probability: 0.9, domain: "a.com" },
        { event_id: 2, citation_index: 2, relation: "supports", probability: 0.4, domain: "b.com" },
      ],
    });
    expect(windowConsistency([c], events, W).outcomes[0].status).toBe("uncorroborated");
  });

  it("ignores neutral judgments", () => {
    const events = [ev(1, "a.com", 0.9, inWindow), ev(2, "b.com", 0.8, inWindow)];
    const c = claim({
      evidence: [
        { event_id: 1, citation_index: 1, relation: "supports", probability: 0.9, domain: "a.com" },
        { event_id: 2, citation_index: 2, relation: "neutral", probability: 0.99, domain: "b.com" },
      ],
    });
    expect(windowConsistency([c], events, W).outcomes[0].status).toBe("uncorroborated");
  });

  it("keeps only the strongest judgment per domain", () => {
    const events = [ev(1, "a.com", 0.9, inWindow), ev(2, "a.com", 0.9, inWindow), ev(3, "b.com", 0.9, inWindow)];
    const c = claim({
      evidence: [
        { event_id: 1, citation_index: 1, relation: "supports", probability: 0.7, domain: "a.com" },
        { event_id: 2, citation_index: 2, relation: "supports", probability: 0.95, domain: "a.com" },
        { event_id: 3, citation_index: 3, relation: "supports", probability: 0.9, domain: "b.com" },
      ],
    });
    const r = windowConsistency([c], events, W);
    // a.com contributes once, at its strongest: 0.9*0.95 + 0.9*0.9.
    expect(r.outcomes[0].support).toBeCloseTo(0.9 * 0.95 + 0.9 * 0.9, 6);
  });

  it("has no score when there are no claims", () => {
    const r = windowConsistency([], [], W);
    expect(r.mode).toBe("countsOnly");
    expect(r.outcomes).toEqual([]);
  });
});

describe("consistencyTrusted", () => {
  const base: Hotspot = {
    hotspot_id: 1, lat: 0, lon: 0, conf_score: 0, convergence_score: null,
    alert_level: "Medium", event_count: 0, name: null,
    start_window: null, end_window: null, created_at: null,
  };

  it("is true when the full-range recomputation reproduces the published score", () => {
    const events = [ev(1, "a.com", 0.9, inWindow), ev(2, "b.com", 0.8, inWindow)];
    const c = claim({
      evidence: [
        { event_id: 1, citation_index: 1, relation: "supports", probability: 0.9, domain: "a.com" },
        { event_id: 2, citation_index: 2, relation: "supports", probability: 0.9, domain: "b.com" },
      ],
    });
    expect(consistencyTrusted([c], events, { ...base, consistency_score: 100 })).toBe(true);
  });

  it("is false when the server used a different NLI threshold", () => {
    const events = [ev(1, "a.com", 0.9, inWindow), ev(2, "b.com", 0.8, inWindow)];
    const c = claim({
      evidence: [
        { event_id: 1, citation_index: 1, relation: "supports", probability: 0.9, domain: "a.com" },
        { event_id: 2, citation_index: 2, relation: "supports", probability: 0.9, domain: "b.com" },
      ],
    });
    expect(consistencyTrusted([c], events, { ...base, consistency_score: 50 })).toBe(false);
  });
});
