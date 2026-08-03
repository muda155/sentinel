import { describe, it, expect } from "vitest";
import { sortHotspots, TRIAGE_SORTS, TRIAGE_SORT_LABEL, type TriageSort } from "@/lib/triage";
import type { Hotspot } from "@/lib/api";

const h = (over: Partial<Hotspot>): Hotspot => ({
  hotspot_id: 1, lat: 0, lon: 0, conf_score: 50, convergence_score: 50,
  alert_level: "Medium", event_count: 1, consistency_score: null, name: null,
  start_window: null, end_window: null, created_at: null, ...over,
});

describe("sortHotspots", () => {
  it("orders Critical before High before Medium", () => {
    const out = sortHotspots(
      [h({ hotspot_id: 1, alert_level: "Medium" }),
       h({ hotspot_id: 2, alert_level: "Critical" }),
       h({ hotspot_id: 3, alert_level: "High" })],
      "alert",
    );
    expect(out.map((x) => x.hotspot_id)).toEqual([2, 3, 1]);
  });

  it("breaks ties by confidence, then by id — never by input order", () => {
    // A stable, total order matters: the rail re-sorts on every SSE refetch,
    // and rows jumping around under the cursor makes it unusable.
    const out = sortHotspots(
      [h({ hotspot_id: 9, alert_level: "High", conf_score: 40 }),
       h({ hotspot_id: 4, alert_level: "High", conf_score: 80 }),
       h({ hotspot_id: 2, alert_level: "High", conf_score: 40 })],
      "alert",
    );
    expect(out.map((x) => x.hotspot_id)).toEqual([4, 2, 9]);
  });

  it("sorts descending for conf, convergence and events", () => {
    const data = [h({ hotspot_id: 1, conf_score: 10, convergence_score: 90, event_count: 5 }),
                  h({ hotspot_id: 2, conf_score: 90, convergence_score: 10, event_count: 50 })];
    expect(sortHotspots(data, "conf").map((x) => x.hotspot_id)).toEqual([2, 1]);
    expect(sortHotspots(data, "convergence").map((x) => x.hotspot_id)).toEqual([1, 2]);
    expect(sortHotspots(data, "events").map((x) => x.hotspot_id)).toEqual([2, 1]);
  });

  it("sorts 'recent' by end_window, falling back to created_at", () => {
    const out = sortHotspots(
      [h({ hotspot_id: 1, end_window: "2026-08-01T00:00:00Z" }),
       h({ hotspot_id: 2, end_window: null, created_at: "2026-08-03T00:00:00Z" }),
       h({ hotspot_id: 3, end_window: "2026-08-02T00:00:00Z" })],
      "recent",
    );
    expect(out.map((x) => x.hotspot_id)).toEqual([2, 3, 1]);
  });

  it("sinks undated and malformed rows instead of throwing", () => {
    const out = sortHotspots(
      [h({ hotspot_id: 1, end_window: "not-a-date" }),
       h({ hotspot_id: 2, end_window: "2026-08-02T00:00:00Z" })],
      "recent",
    );
    expect(out.map((x) => x.hotspot_id)).toEqual([2, 1]);
  });

  it("does not mutate its input", () => {
    // app/page.tsx memoizes on array reference; an in-place sort would make
    // the cluster index and the rail disagree about ordering.
    const data = [h({ hotspot_id: 1, conf_score: 10 }), h({ hotspot_id: 2, conf_score: 90 })];
    const before = data.map((x) => x.hotspot_id);
    sortHotspots(data, "conf");
    expect(data.map((x) => x.hotspot_id)).toEqual(before);
  });

  it("gives every sort an i18n key", () => {
    for (const s of TRIAGE_SORTS) expect(TRIAGE_SORT_LABEL[s as TriageSort]).toMatch(/^triage\.sort\./);
  });
});
