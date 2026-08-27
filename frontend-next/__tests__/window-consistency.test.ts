import { describe, expect, it } from "vitest";
import { claimValue, consistencyTrusted, windowConsistency } from "@/lib/window-consistency";
import parity from "../../tests/fixtures/claim_value_parity.json";
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
  // Cross-check against pipeline/consistency.py. The agreement discount lives in
  // two copies and consistencyTrusted() compares them, so a one-sided edit does
  // not throw -- it silently fails every reconstruction and drops CompareDialog
  // to countsOnly. The expected value below was produced by the Python side.
  it("discounts a corroborated claim by the share of evidence contradicting it", () => {
    const events = [
      ev(1, "a.com", 0.9, inWindow), ev(2, "b.com", 0.8, inWindow),
      ev(3, "c.com", 0.5, inWindow),
    ];
    const c = claim({
      evidence: [
        { event_id: 1, citation_index: 1, relation: "supports", probability: 0.9, domain: "a.com" },
        { event_id: 2, citation_index: 2, relation: "supports", probability: 0.9, domain: "b.com" },
        { event_id: 3, citation_index: 3, relation: "contradicts", probability: 0.9, domain: "c.com" },
      ],
    });
    const r = windowConsistency([c], events, W);
    // support 1.53, dispute 0.45 -- below DISPUTE_RATIO * support, so the
    // status survives and only the value is discounted.
    expect(r.outcomes[0].status).toBe("corroborated");
    if (r.mode === "score") expect(r.score).toBeCloseTo(77.27272727272728, 9);
  });

  it("scores a claim nobody contradicted at its full status ceiling", () => {
    const events = [ev(1, "a.com", 0.9, inWindow), ev(2, "b.com", 0.8, inWindow)];
    const c = claim({
      evidence: [
        { event_id: 1, citation_index: 1, relation: "supports", probability: 0.9, domain: "a.com" },
        { event_id: 2, citation_index: 2, relation: "supports", probability: 0.9, domain: "b.com" },
      ],
    });
    const r = windowConsistency([c], events, W);
    if (r.mode === "score") expect(r.score).toBeCloseTo(100, 9);
  });

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

  it("marks a claim unverifiable when none of its evidence falls in the window", () => {
    // A claim extracted from the full event set may have no evidence in a given
    // window. Judging it anyway yields exactly 50 (every claim uncorroborated
    // at weight 0.1) and reads as a measurement — it must be countsOnly.
    const events = [ev(1, "a.com", 0.9, inWindow)];
    const c = claim({
      evidence: [{ event_id: 9, citation_index: 9, relation: "supports", probability: 0.9, domain: "a.com" }],
    });
    const r = windowConsistency([c], events, W);
    expect(r.outcomes[0].status).toBe("unverifiable");
    expect(r.mode).toBe("countsOnly");
  });

  it("is countsOnly, not a fabricated 50, when the window has no events", () => {
    const events = [ev(1, "a.com", 0.9, inWindow)];
    const c = claim({
      evidence: [{ event_id: 1, citation_index: 1, relation: "supports", probability: 0.9, domain: "a.com" }],
    });
    const emptyW = { from: "2026-08-10T00:00:00Z", to: "2026-08-11T00:00:00Z" };
    const r = windowConsistency([c], events, emptyW);
    expect(r.mode).toBe("countsOnly");
    expect(r.outcomes[0].status).toBe("unverifiable");
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

// --- FR-22(d) agreement-scaled claim value (changed 2026-08-20) -------------

describe("claimValue", () => {
  // The fixture is generated from pipeline/consistency.py:claim_value by
  // tests/test_consistency_parity.py. This is the only mechanism stopping the
  // Python engine and this port from drifting apart: a one-sided edit fails
  // nothing at runtime, it just makes consistencyTrusted() always false and
  // pins CompareDialog to counts-only forever.
  it.each(parity.cases)(
    "matches the Python engine for $status support=$support dispute=$dispute",
    (c) => {
      const outcome = {
        claim_id: 1, text: "c", status: c.status as "corroborated" | "uncorroborated" | "disputed",
        support: c.support, dispute: c.dispute, weight: c.weight,
      };
      expect(claimValue(outcome)).toBeCloseTo(c.value, 12);
    },
  );

  it("leaves a claim with no dispute exactly at its status value", () => {
    for (const [status, expected] of [
      ["corroborated", 1.0], ["uncorroborated", 0.5], ["disputed", 0.0],
    ] as const) {
      expect(claimValue({
        claim_id: 1, text: "c", status, support: 4.0, dispute: 0, weight: 4.0,
      })).toBeCloseTo(expected, 12);
    }
  });

  it("keeps the status value when support and dispute are both zero", () => {
    expect(claimValue({
      claim_id: 1, text: "c", status: "uncorroborated",
      support: 0, dispute: 0, weight: 0.1,
    })).toBeCloseTo(0.5, 12);
  });

  it("never rises as dispute grows", () => {
    const values = [0, 0.1, 0.5, 1, 2, 5, 50].map((dispute) => claimValue({
      claim_id: 1, text: "c", status: "corroborated",
      support: 2, dispute, weight: Math.max(2 + dispute, 0.1),
    }));
    expect(values).toEqual([...values].sort((a, b) => b - a));
  });
});

describe("windowConsistency with the agreement penalty", () => {
  it("scores a clean corroborated claim exactly as before the change", () => {
    const events = [ev(1, "a.com", 0.9, inWindow), ev(2, "b.com", 0.8, inWindow)];
    const c = claim({
      evidence: [
        { event_id: 1, citation_index: 1, relation: "supports", probability: 0.9, domain: "a.com" },
        { event_id: 2, citation_index: 2, relation: "supports", probability: 0.9, domain: "b.com" },
      ],
    });
    const r = windowConsistency([c], events, W);
    expect(r.mode).toBe("score");
    if (r.mode === "score") expect(r.score).toBeCloseTo(100, 6);
  });

  it("discounts a corroborated claim that carries a contradiction", () => {
    // Three supporters keep it corroborated (dispute < 0.5 * support), but the
    // contradicting domain must now cost it something.
    const events = [
      ev(1, "a.com", 0.9, inWindow), ev(2, "b.com", 0.9, inWindow),
      ev(3, "c.com", 0.9, inWindow), ev(4, "d.com", 0.4, inWindow),
    ];
    const c = claim({
      evidence: [
        { event_id: 1, citation_index: 1, relation: "supports", probability: 0.9, domain: "a.com" },
        { event_id: 2, citation_index: 2, relation: "supports", probability: 0.9, domain: "b.com" },
        { event_id: 3, citation_index: 3, relation: "supports", probability: 0.9, domain: "c.com" },
        { event_id: 4, citation_index: 4, relation: "contradicts", probability: 0.9, domain: "d.com" },
      ],
    });
    const r = windowConsistency([c], events, W);
    expect(r.mode).toBe("score");
    if (r.mode !== "score") return;
    expect(r.outcomes[0].status).toBe("corroborated");
    expect(r.score).toBeLessThan(100);
    // support = 3 * 0.9 * 0.9 = 2.43, dispute = 0.4 * 0.9 = 0.36
    expect(r.score).toBeCloseTo((100 * 2.43) / (2.43 + 0.36), 6);
  });
});
