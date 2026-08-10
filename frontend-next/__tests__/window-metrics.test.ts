import { describe, expect, it } from "vitest";
import { confTrusted, diversity, eventsInWindow, sourceDensity, windowMetrics } from "@/lib/window-metrics";
import type { Hotspot, HotspotEvent } from "@/lib/api";

const ev = (o: Partial<HotspotEvent>): HotspotEvent => ({
  event_id: 1, title: null, url: null, domain: "a.com",
  source_system: "GDELT", event_type_label: "military_conflict",
  event_date: "2026-08-05T00:00:00Z",
  goldstein_scale: null, avg_tone: null, num_sources: null, fatalities: null,
  duplicate_count: 1, trust_tier: 1, trust_score: 0.9,
  country_code: "US", citation_index: 1, ...o,
});

const W = { from: "2026-08-05T00:00:00Z", to: "2026-08-06T00:00:00Z" };

describe("eventsInWindow", () => {
  it("includes the lower bound and excludes the upper", () => {
    const events = [
      ev({ event_id: 1, event_date: "2026-08-05T00:00:00Z" }),
      ev({ event_id: 2, event_date: "2026-08-05T12:00:00Z" }),
      ev({ event_id: 3, event_date: "2026-08-06T00:00:00Z" }),
      ev({ event_id: 4, event_date: "2026-08-04T23:59:59Z" }),
    ];
    expect(eventsInWindow(events, W).map((e) => e.event_id)).toEqual([1, 2]);
  });
});

describe("sourceDensity", () => {
  it("sums trust over UNIQUE domains and squashes with tanh", () => {
    // Two events from one domain must count once: tanh(0.9/3).
    const events = [ev({ event_id: 1, domain: "a.com" }), ev({ event_id: 2, domain: "a.com" })];
    expect(sourceDensity(events)).toBeCloseTo(Math.tanh(0.9 / 3), 6);
  });

  it("is null with no events, since nothing was measured", () => {
    expect(sourceDensity([])).toBeNull();
  });
});

describe("diversity", () => {
  it("is zero when every source sits in one country", () => {
    expect(diversity([ev({ domain: "a.com", country_code: "US" }), ev({ domain: "b.com", country_code: "US" })])).toBe(0);
  });

  it("is 1 for an even split across two countries", () => {
    expect(diversity([ev({ domain: "a.com", country_code: "US" }), ev({ domain: "b.com", country_code: "GB" })])).toBeCloseTo(1, 6);
  });

  it("ignores events with no country code", () => {
    const events = [ev({ domain: "a.com", country_code: "US" }), ev({ domain: "b.com", country_code: null })];
    expect(diversity(events)).toBe(0);
  });
});

describe("windowMetrics", () => {
  it("reports counts, fatalities and tone over the window only", () => {
    const events = [
      ev({ event_id: 1, domain: "a.com", fatalities: 3, avg_tone: -2, event_date: "2026-08-05T01:00:00Z" }),
      ev({ event_id: 2, domain: "b.com", fatalities: 9, avg_tone: -4, event_date: "2026-08-05T02:00:00Z" }),
      ev({ event_id: 3, domain: "c.com", fatalities: 99, avg_tone: 0, event_date: "2026-08-09T00:00:00Z" }),
    ];
    const m = windowMetrics(events, W);
    expect(m.eventCount).toBe(2);
    expect(m.uniqueDomains).toBe(2);
    expect(m.maxFatalities).toBe(9);
    expect(m.meanTone).toBeCloseTo(-3, 6);
  });

  it("reports convergence as typesOnly, since the published score is cell-derived", () => {
    const m = windowMetrics([ev({ domain: "a.com" }), ev({ event_id: 2, domain: "b.com", event_type_label: "civil_unrest" })], W);
    expect(m.convergence.mode).toBe("typesOnly");
    expect(m.convergence.types).toBe(2);
  });

  it("has null tone when no event in the window carries one", () => {
    expect(windowMetrics([ev({ avg_tone: null })], W).meanTone).toBeNull();
  });

  it("has null conf and null source density for an empty window", () => {
    // An empty window must not render "Confidence 0.0 ↑ 70.0 +70.0" — a score
    // of zero implies a measurement, not an absence of events.
    const m = windowMetrics([ev({ event_date: "2026-08-09T00:00:00Z" })], W);
    expect(m.eventCount).toBe(0);
    expect(m.sourceDensity).toBeNull();
    expect(m.diversity).toBeNull();
    expect(m.conf).toBeNull();
  });
});

describe("confTrusted", () => {
  const base: Hotspot = {
    hotspot_id: 1, lat: 0, lon: 0, conf_score: 0, convergence_score: null,
    alert_level: "Medium", event_count: 0, name: null,
    start_window: null, end_window: null, created_at: null,
  };

  it("is true when the full-range recomputation reproduces the published score", () => {
    const events = [ev({ domain: "a.com", country_code: "US" }), ev({ event_id: 2, domain: "b.com", country_code: "GB", trust_score: 0.9 })];
    const conf = (0.7 * Math.tanh(1.8 / 3) + 0.3 * 1) * 100;
    expect(confTrusted(events, { ...base, conf_score: conf })).toBe(true);
  });

  it("is false when the server used different weights", () => {
    const events = [ev({ domain: "a.com", country_code: "US" })];
    expect(confTrusted(events, { ...base, conf_score: 12.5 })).toBe(false);
  });
});
