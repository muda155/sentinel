import { describe, it, expect } from "vitest";
import type { Hotspot } from "@/lib/api";
import { createClusterIndex, getClusterData, getExpansionZoom, ClusterResult } from "@/lib/clustering";

function makeHotspot(overrides: Partial<Hotspot> & { lat: number; lon: number }): Hotspot {
  return {
    hotspot_id: 0,
    conf_score: 50,
    convergence_score: 50,
    alert_level: "Medium",
    event_count: 1,
    name: null,
    end_window: "2026-07-01T00:00:00Z",
    created_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

describe("createClusterIndex", () => {
  it("returns a supercluster instance with loaded data", () => {
    const hotspots = [
      makeHotspot({ hotspot_id: 1, lat: 10, lon: 20 }),
      makeHotspot({ hotspot_id: 2, lat: 11, lon: 21 }),
    ];
    const index = createClusterIndex(hotspots);
    expect(index).toBeDefined();
    // Should return clusters at zoom 0 covering the world
    const clusters = index.getClusters([-180, -90, 180, 90], 0);
    expect(clusters.length).toBeGreaterThan(0);
  });

  it("handles empty array", () => {
    const index = createClusterIndex([]);
    const clusters = index.getClusters([-180, -90, 180, 90], 0);
    expect(clusters).toEqual([]);
  });
});

describe("getClusterData", () => {
  it("returns clusters and leaves separately", () => {
    // Put 5 hotspots close together so they cluster at low zoom
    const hotspots = Array.from({ length: 5 }, (_, i) =>
      makeHotspot({ hotspot_id: i, lat: 10.001 + i * 0.001, lon: 20.001 + i * 0.001 })
    );
    const index = createClusterIndex(hotspots);
    const result = getClusterData(index, [-180, -90, 180, 90], 0);
    expect(result).toHaveProperty("clusters");
    expect(result).toHaveProperty("leaves");
    // At zoom 0, these 5 close points should form at least 1 cluster
    expect(result.clusters.length).toBeGreaterThanOrEqual(1);
    // Each cluster has point_count
    expect(result.clusters[0].point_count).toBe(5);
  });

  it("separates distant points as leaves at low zoom", () => {
    const hotspots = [
      makeHotspot({ hotspot_id: 1, lat: 10, lon: 20 }),
      makeHotspot({ hotspot_id: 2, lat: -30, lon: 150 }),
    ];
    const index = createClusterIndex(hotspots);
    const result = getClusterData(index, [-180, -90, 180, 90], 0);
    // Two very distant points should remain as leaves, not cluster
    expect(result.leaves.length).toBe(2);
    expect(result.clusters.length).toBe(0);
  });

  it("preserves hotspot data on leaf features", () => {
    const hotspot = makeHotspot({ hotspot_id: 42, lat: 10, lon: 20, conf_score: 85, alert_level: "Critical" });
    const index = createClusterIndex([hotspot]);
    const result = getClusterData(index, [-180, -90, 180, 90], 5);
    expect(result.leaves.length).toBe(1);
    expect(result.leaves[0].hotspot_id).toBe(42);
    expect(result.leaves[0].conf_score).toBe(85);
    expect(result.leaves[0].alert_level).toBe("Critical");
  });

  it("returns empty result for empty index", () => {
    const index = createClusterIndex([]);
    const result = getClusterData(index, [-180, -90, 180, 90], 0);
    expect(result.clusters).toEqual([]);
    expect(result.leaves).toEqual([]);
  });
});

describe("getExpansionZoom", () => {
  it("returns a finite zoom deeper than the clustered view", () => {
    const hotspots = Array.from({ length: 5 }, (_, i) =>
      makeHotspot({ hotspot_id: i, lat: 10.001 + i * 0.001, lon: 20.001 + i * 0.001 })
    );
    const index = createClusterIndex(hotspots);
    const { clusters } = getClusterData(index, [-180, -90, 180, 90], 0);
    expect(clusters.length).toBeGreaterThanOrEqual(1);
    const zoom = getExpansionZoom(index, clusters[0].cluster_id);
    expect(Number.isFinite(zoom)).toBe(true);
    expect(zoom).toBeGreaterThan(0);
  });
});
