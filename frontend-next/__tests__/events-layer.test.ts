import { describe, it, expect } from "vitest";
import { bboxFromBounds, quantizeBbox, bboxKey, windowRange, type Bbox } from "@/lib/events-layer";

describe("bboxFromBounds", () => {
  it("accepts the flat [w, s, e, n] shape", () => {
    expect(bboxFromBounds([-10, -5, 10, 5]))
      .toEqual({ sw_lat: -5, sw_lon: -10, ne_lat: 5, ne_lon: 10 });
  });
  it("accepts the nested [[w, s], [e, n]] shape", () => {
    // deck.gl's WebMercatorViewport.getBounds() has returned both shapes
    // across major versions; accept either rather than pinning to one.
    expect(bboxFromBounds([[-10, -5], [10, 5]]))
      .toEqual({ sw_lat: -5, sw_lon: -10, ne_lat: 5, ne_lon: 10 });
  });
  it("returns null for anything else instead of producing NaN params", () => {
    expect(bboxFromBounds(null)).toBeNull();
    expect(bboxFromBounds([1, 2, 3])).toBeNull();
    expect(bboxFromBounds([1, 2, "x", 4])).toBeNull();
  });
});

describe("quantizeBbox", () => {
  it("expands outward to whole degrees so small pans do not refetch", () => {
    const a = quantizeBbox({ sw_lat: 10.2, sw_lon: 20.7, ne_lat: 11.1, ne_lon: 21.4 });
    const b = quantizeBbox({ sw_lat: 10.9, sw_lon: 20.1, ne_lat: 11.9, ne_lon: 21.9 });
    expect(a).toEqual({ sw_lat: 10, sw_lon: 20, ne_lat: 12, ne_lon: 22 });
    expect(bboxKey(a)).toBe(bboxKey(b));
  });
  it("clamps to valid lat/lon so the API never sees an out-of-range envelope", () => {
    const q = quantizeBbox({ sw_lat: -95, sw_lon: -190, ne_lat: 95, ne_lon: 190 });
    expect(q).toEqual({ sw_lat: -90, sw_lon: -180, ne_lat: 90, ne_lon: 180 });
  });
});

describe("windowRange", () => {
  it("spans exactly the filter window, ending now", () => {
    const now = Date.parse("2026-08-03T12:00:00.000Z");
    expect(windowRange("24h", now)).toEqual({
      start: "2026-08-02T12:00:00.000Z", end: "2026-08-03T12:00:00.000Z",
    });
    expect(windowRange("7d", now).start).toBe("2026-07-27T12:00:00.000Z");
  });
});
