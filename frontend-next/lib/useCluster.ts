import { useMemo } from "react";
import type { Hotspot } from "@/lib/api";
import { createClusterIndex, getClusterData, type ClusterFeature } from "@/lib/clustering";

interface ClusterHookResult {
  clusters: ClusterFeature[];
  leaves: Hotspot[];
  /** Supercluster index, cast to any — only used for getClusterExpansionZoom(). */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  index: any;
}

/**
 * Hook that maintains a supercluster index and returns clusters + leaves
 * for the current viewport bounding box and zoom level.
 * Rebuilds the index only when hotspots change.
 */
export function useCluster(
  hotspots: Hotspot[],
  bounds: [number, number, number, number] | null,
  zoom: number,
): ClusterHookResult {
  // Stable key avoids rebuilding the index on every parent re-render
  // when the hotspot array identity changes but content hasn't (≤200 items).
  const hotspotKey = hotspots.length > 0
    ? hotspots.map((h) => h.hotspot_id).join(",")
    : "";

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const index: any = useMemo(() => createClusterIndex(hotspots), [hotspotKey]);

  return useMemo(() => {
    if (!bounds || hotspots.length === 0) {
      return { clusters: [], leaves: [], index };
    }
    return { ...getClusterData(index, bounds, zoom), index };
  }, [index, bounds, zoom, hotspots.length]);
}
