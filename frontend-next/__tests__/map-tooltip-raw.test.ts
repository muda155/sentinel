import { describe, it, expect } from "vitest";
import { mapTooltip, RAW_EVENT_LAYER_ID } from "@/lib/map-tooltip";
import type { EventFeature } from "@/lib/api";

const t = (key: string) => key;

const feat = (over: Partial<EventFeature["properties"]>): EventFeature => ({
  type: "Feature",
  geometry: { type: "Point", coordinates: [30, 40] },
  properties: {
    event_id: 7, event_date: "2026-07-28T12:00:00Z", cameo_code: null,
    country_code: null, url: null, title: null, ...over,
  },
});

const pick = (object: EventFeature) => ({ layer: { id: RAW_EVENT_LAYER_ID }, object });

describe("mapTooltip raw-events branch", () => {
  it("prefers the GKG title", () => {
    const tip = mapTooltip(pick(feat({ title: "Dove Fire Arrest" })), t);
    expect(tip?.text).toBe("Dove Fire Arrest\n2026-07-28");
  });

  it("falls back to the URL host when there is no title", () => {
    const tip = mapTooltip(pick(feat({ url: "https://example.com/article" })), t);
    expect(tip?.text).toBe("example.com\n2026-07-28");
  });

  it("falls back to #id with neither a title nor a usable host", () => {
    expect(mapTooltip(pick(feat({ url: "not a url" })), t)?.text).toBe("#7\n2026-07-28");
    expect(mapTooltip(pick(feat()), t)?.text).toBe("#7\n2026-07-28");
  });

  it("omits the date line when event_date is absent", () => {
    const p = feat({ event_date: null as unknown as string });
    expect(mapTooltip(pick(p), t)?.text).toBe("#7");
  });

  it("ignores raw-shaped objects picked from other layers", () => {
    expect(mapTooltip({ layer: { id: "hotspots" }, object: feat() }, t)).toBeNull();
  });
});
