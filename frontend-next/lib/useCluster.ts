import { useMemo } from "react";
import type { Hotspot } from "@/lib/api";
import { createClusterIndex, getClusterData, type ClusterFeature } from "@/lib/clustering";

interface ClusterHookResult {
  clusters: ClusterFeature[];
  leaves: Hotspot[];
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
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const index: any = useMemo(() => createClusterIndex(hotspots), [hotspots]);

  return useMemo(() => {
    if (!bounds || hotspots.length === 0) {
      return { clusters: [], leaves: [] };
    }
    return getClusterData(index, bounds, zoom);
  }, [index, bounds, zoom, hotspots.length]);
}
