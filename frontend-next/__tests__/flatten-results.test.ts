import { describe, it, expect } from "vitest";
import { flattenResults } from "@/lib/flatten-results";
import type { SearchResults, Hotspot } from "@/lib/api";

const h = (id: number): Hotspot => ({
  hotspot_id: id, lat: 1, lon: 2, conf_score: 50, convergence_score: 60,
  alert_level: "High", event_count: 3, name: `H${id}`,
});

describe("flattenResults", () => {
  it("flattens groups in order hotspots, events, sources for keyboard nav", () => {
    const res: SearchResults = {
      hotspots: [h(1)],
      events: [{ event_id: 9, title: "x", url: "u", domain: "d",
                 event_date: "2026-06-10", hotspot: h(2) }],
      sources: [{ source_id: 3, domain: "reuters.com", trust_tier: 1, hotspots: [h(4)] }],
    };
    const flat = flattenResults(res);
    expect(flat.map((f) => f.group)).toEqual(["hotspots", "events", "sources"]);
    expect(flat[0].hotspot?.hotspot_id).toBe(1);
    expect(flat[1].hotspot?.hotspot_id).toBe(2);
    expect(flat[2].hotspot).toBeUndefined();
    expect(flat[2].sourceHotspots?.[0].hotspot_id).toBe(4);
  });
  it("returns empty for empty groups", () => {
    expect(flattenResults({ hotspots: [], events: [], sources: [] })).toEqual([]);
  });
});
