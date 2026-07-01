import { useCallback, useMemo } from "react";
import type { Hotspot } from "@/lib/api";
import {
  createClusterIndex,
  getClusterData,
  getExpansionZoom,
  type ClusterFeature,
} from "@/lib/clustering";

interface ClusterHookResult {
  clusters: ClusterFeature[];
  leaves: Hotspot[];
  /** Zoom at which a cluster expands into its children (for click-to-zoom). */
  getExpansionZoom: (clusterId: number) => number;
}

/**
 * Maintains a supercluster index and returns clusters + leaves for the current
 * viewport bounding box and zoom level. The index is rebuilt only when the
 * `hotspots` reference changes, so callers must pass a stable (memoized) array
 * to avoid rebuilding on unrelated re-renders.
 */
export function useCluster(
  hotspots: Hotspot[],
  bounds: [number, number, number, number] | null,
  zoom: number,
): ClusterHookResult {
  const index = useMemo(() => createClusterIndex(hotspots), [hotspots]);

  const expansionZoom = useCallback(
    (clusterId: number) => getExpansionZoom(index, clusterId),
    [index],
  );

  const data = useMemo(() => {
    if (!bounds) return { clusters: [], leaves: [] };
    return getClusterData(index, bounds, zoom);
  }, [index, bounds, zoom]);

  return { ...data, getExpansionZoom: expansionZoom };
}
