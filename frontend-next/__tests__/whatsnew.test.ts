import { describe, it, expect, beforeEach } from "vitest";
import type { Hotspot } from "@/lib/api";
import { isNew, countNew, markSeen, getLastSeen, LAST_SEEN_KEY } from "@/lib/whatsnew";

function makeHotspot(overrides: Partial<Hotspot> & { created_at: string }): Hotspot {
  return {
    hotspot_id: 0,
    lat: 0,
    lon: 0,
    conf_score: 50,
    convergence_score: 50,
    alert_level: "Medium",
    event_count: 1,
    name: null,
    start_window: null,
    end_window: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

describe("LAST_SEEN_KEY", () => {
  it("is sentinel_hotspots_last_seen", () => {
    expect(LAST_SEEN_KEY).toBe("sentinel_hotspots_last_seen");
  });
});

describe("isNew", () => {
  it("returns true for hotspot created after lastSeen", () => {
    expect(isNew("2026-07-02T00:00:00Z", 1000000)).toBe(true);
  });

  it("returns false for hotspot created before lastSeen", () => {
    expect(isNew("2026-06-01T00:00:00Z", 2000000000000)).toBe(false);
  });

  it("returns false for hotspot created exactly at lastSeen boundary", () => {
    // created_at "2026-07-01T12:00:00Z" = 1719820800000 ms epoch
    const epoch = new Date("2026-07-01T12:00:00Z").getTime();
    expect(isNew("2026-07-01T12:00:00Z", epoch)).toBe(false);
  });

  it("returns true when lastSeen is 0 (epoch 0 = unset)", () => {
    // Everything after epoch 0 is new
    expect(isNew("1970-01-01T00:00:01Z", 0)).toBe(true);
  });

  it("returns false for malformed created_at string", () => {
    expect(isNew("not-a-date", 1000000)).toBe(false);
  });
});

describe("countNew", () => {
  const hotspots: Hotspot[] = [
    makeHotspot({ hotspot_id: 1, created_at: "2026-07-01T10:00:00Z" }),
    makeHotspot({ hotspot_id: 2, created_at: "2026-07-01T12:00:00Z" }),
    makeHotspot({ hotspot_id: 3, created_at: "2026-07-01T14:00:00Z" }),
    makeHotspot({ hotspot_id: 4, created_at: "2026-07-02T08:00:00Z" }),
  ];

  it("counts hotspots created after lastSeen", () => {
    // lastSeen = 2026-07-01T11:00:00Z
    const lastSeen = new Date("2026-07-01T11:00:00Z").getTime();
    expect(countNew(hotspots, lastSeen)).toBe(3); // ids 2,3,4
  });

  it("returns 0 when no hotspots are new", () => {
    const lastSeen = new Date("2026-07-03T00:00:00Z").getTime();
    expect(countNew(hotspots, lastSeen)).toBe(0);
  });

  it("returns 0 for empty hotspot array", () => {
    expect(countNew([], 0)).toBe(0);
  });
});

describe("localStorage integration", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("getLastSeen returns 0 when nothing stored", () => {
    expect(getLastSeen()).toBe(0);
  });

  it("markSeen stores the current timestamp", () => {
    markSeen();
    const stored = localStorage.getItem(LAST_SEEN_KEY);
    expect(stored).not.toBeNull();
    expect(Number(stored)).toBeGreaterThan(0);
  });

  it("getLastSeen reads back the stored value", () => {
    localStorage.setItem(LAST_SEEN_KEY, "1234567890");
    expect(getLastSeen()).toBe(1234567890);
  });
});
