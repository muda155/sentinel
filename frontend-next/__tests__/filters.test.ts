import { describe, it, expect } from "vitest";
import {
  AlertLevel,
  TimeWindow,
  TIME_WINDOW_HOURS,
  HotspotFilters,
  DEFAULT_FILTERS,
  passesFilter,
  applyFilters,
} from "@/lib/filters";
import { Hotspot } from "@/lib/api";

function makeHotspot(overrides: Partial<Hotspot>): Hotspot {
  return {
    hotspot_id: 1,
    lat: 10,
    lon: 20,
    conf_score: 50,
    convergence_score: 50,
    alert_level: "Medium",
    event_count: 5,
    name: "Test",
    end_window: new Date().toISOString(),
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("passesFilter", () => {
  it("default floor (minConf=40) hides grey hotspots below 40", () => {
    const h = makeHotspot({ conf_score: 39.9 });
    expect(passesFilter(h, DEFAULT_FILTERS)).toBe(false);
  });

  it("default floor shows hotspots at exactly 40", () => {
    const h = makeHotspot({ conf_score: 40 });
    expect(passesFilter(h, DEFAULT_FILTERS)).toBe(true);
  });

  it("confidence slider excludes below-threshold hotspots", () => {
    const h = makeHotspot({ conf_score: 30 });
    const filters: HotspotFilters = { ...DEFAULT_FILTERS, minConf: 50 };
    expect(passesFilter(h, filters)).toBe(false);
  });

  it("confidence slider includes above-threshold hotspots", () => {
    const h = makeHotspot({ conf_score: 60 });
    const filters: HotspotFilters = { ...DEFAULT_FILTERS, minConf: 50 };
    expect(passesFilter(h, filters)).toBe(true);
  });

  it("alert-level include set filters correctly", () => {
    const includeSet = new Set<AlertLevel>(["Critical", "High"]);
    const filters: HotspotFilters = { ...DEFAULT_FILTERS, alertLevels: includeSet };
    expect(passesFilter(makeHotspot({ alert_level: "Critical" }), filters)).toBe(true);
    expect(passesFilter(makeHotspot({ alert_level: "High" }), filters)).toBe(true);
    expect(passesFilter(makeHotspot({ alert_level: "Medium" }), filters)).toBe(false);
  });

  it("empty alert-level set passes everything (no constraint)", () => {
    const filters: HotspotFilters = { ...DEFAULT_FILTERS, alertLevels: new Set() };
    expect(passesFilter(makeHotspot({ alert_level: "Medium" }), filters)).toBe(true);
  });

  it("time window filters by end_window (within range)", () => {
    const h = makeHotspot({ end_window: new Date().toISOString() });
    const filters: HotspotFilters = { ...DEFAULT_FILTERS, timeWindow: "24h" };
    expect(passesFilter(h, filters)).toBe(true);
  });

  it("time window excludes events outside the window", () => {
    const past = new Date();
    past.setHours(past.getHours() - 48);
    const h = makeHotspot({ end_window: past.toISOString() });
    const filters: HotspotFilters = { ...DEFAULT_FILTERS, timeWindow: "24h" };
    expect(passesFilter(h, filters)).toBe(false);
  });

  it("'7d' time window always passes for recent hotspots", () => {
    const h = makeHotspot({ end_window: new Date().toISOString() });
    const filters: HotspotFilters = { ...DEFAULT_FILTERS, timeWindow: "7d" };
    expect(passesFilter(h, filters)).toBe(true);
  });

  it("malformed end_window fails open (passes)", () => {
    const h = makeHotspot({ end_window: "not-a-date" });
    const filters: HotspotFilters = { ...DEFAULT_FILTERS, timeWindow: "24h" };
    expect(passesFilter(h, filters)).toBe(true);
  });

  it("null end_window passes (no temporal info)", () => {
    const h = makeHotspot({ end_window: "" });
    const filters: HotspotFilters = { ...DEFAULT_FILTERS, timeWindow: "24h" };
    expect(passesFilter(h, filters)).toBe(true);
  });
});

describe("applyFilters", () => {
  it("returns filtered list and count", () => {
    const hotspots = [
      makeHotspot({ hotspot_id: 1, conf_score: 90, alert_level: "Critical" }),
      makeHotspot({ hotspot_id: 2, conf_score: 30, alert_level: "Medium" }),
      makeHotspot({ hotspot_id: 3, conf_score: 50, alert_level: "High" }),
    ];
    const filters: HotspotFilters = { minConf: 40, alertLevels: new Set(), timeWindow: "7d" };
    const result = applyFilters(hotspots, filters);
    expect(result.filtered).toHaveLength(2);
    expect(result.filtered.map((h) => h.hotspot_id)).toEqual([1, 3]);
    expect(result.total).toBe(3);
  });

  it("DEFAULT_FILTERS has minConf=40, default 7d, all alert levels selected", () => {
    expect(DEFAULT_FILTERS.minConf).toBe(40);
    expect(DEFAULT_FILTERS.timeWindow).toBe("7d");
    expect(DEFAULT_FILTERS.alertLevels).toEqual(new Set(["Critical", "High", "Medium"]));
  });

  it("TIME_WINDOW_HOURS maps the four supported windows", () => {
    expect(TIME_WINDOW_HOURS["24h"]).toBe(24);
    expect(TIME_WINDOW_HOURS["3d"]).toBe(72);
    expect(TIME_WINDOW_HOURS["7d"]).toBe(168);
    expect(TIME_WINDOW_HOURS["30d"]).toBe(720);
  });

  it("hides a 5-day-old hotspot when window is 3d", () => {
    const h = makeHotspot({
      end_window: new Date(Date.now() - 5 * 24 * 3600_000).toISOString(),
    });
    const filters: HotspotFilters = { ...DEFAULT_FILTERS, minConf: 0, timeWindow: "3d" };
    expect(passesFilter(h, filters)).toBe(false);
  });

  it("shows a 5-day-old hotspot when window is 7d", () => {
    const h = makeHotspot({
      end_window: new Date(Date.now() - 5 * 24 * 3600_000).toISOString(),
    });
    const filters: HotspotFilters = { ...DEFAULT_FILTERS, minConf: 0, timeWindow: "7d" };
    expect(passesFilter(h, filters)).toBe(true);
  });
});
