import Supercluster from "supercluster";
import type { Hotspot } from "@/lib/api";

export interface ClusterFeature {
  /** Cluster centroid longitude */
  lon: number;
  /** Cluster centroid latitude */
  lat: number;
  /** Number of points in this cluster */
  point_count: number;
  /** Unique cluster id used for expansion */
  cluster_id: number;
}

export interface ClusterResult {
  clusters: ClusterFeature[];
  leaves: Hotspot[];
}

/** A supercluster index over hotspot points. Encapsulates supercluster so
 *  callers stay decoupled from the library. */
export type HotspotClusterIndex = Supercluster<HotspotProps>;

// Properties stored in supercluster for each hotspot feature.
interface HotspotProps {
  hotspot_id: number;
  conf_score: number;
  convergence_score: number;
  alert_level: string;
  event_count: number;
  name: string | null;
  end_window: string;
  created_at: string;
}

function toProps(h: Hotspot): HotspotProps {
  return {
    hotspot_id: h.hotspot_id,
    conf_score: h.conf_score,
    convergence_score: h.convergence_score,
    alert_level: h.alert_level,
    event_count: h.event_count,
    name: h.name,
    end_window: h.end_window,
    created_at: h.created_at,
  };
}

function fromProps(p: HotspotProps, lon: number, lat: number): Hotspot {
  return {
    hotspot_id: p.hotspot_id,
    lon,
    lat,
    conf_score: p.conf_score,
    convergence_score: p.convergence_score,
    alert_level: p.alert_level as Hotspot["alert_level"],
    event_count: p.event_count,
    name: p.name,
    end_window: p.end_window,
    created_at: p.created_at,
  };
}

/**
 * Create a Supercluster index from hotspots.
 * Configures radius (60px) and maxZoom (12) so clustering activates at world/continent zoom.
 */
export function createClusterIndex(hotspots: Hotspot[]): HotspotClusterIndex {
  const index = new Supercluster<HotspotProps>({
    radius: 60,
    maxZoom: 12,
  });

  const features: Supercluster.PointFeature<HotspotProps>[] = hotspots.map((h) => ({
    type: "Feature",
    geometry: { type: "Point", coordinates: [h.lon, h.lat] },
    properties: toProps(h),
  }));

  index.load(features);
  return index;
}

/**
 * Given a supercluster index and a viewport bounding box + zoom level,
 * return the clusters and unclustered leaf hotspots.
 */
export function getClusterData(
  index: HotspotClusterIndex,
  bbox: [number, number, number, number],
  zoom: number,
): ClusterResult {
  const rawFeatures = index.getClusters(bbox, zoom);

  const clusters: ClusterFeature[] = [];
  const leaves: Hotspot[] = [];

  for (const feature of rawFeatures) {
    const props = feature.properties as Record<string, unknown>;
    if (props.cluster) {
      clusters.push({
        lon: feature.geometry.coordinates[0],
        lat: feature.geometry.coordinates[1],
        point_count: props.point_count as number,
        cluster_id: props.cluster_id as number,
      });
    } else {
      leaves.push(fromProps(
        props as unknown as HotspotProps,
        feature.geometry.coordinates[0],
        feature.geometry.coordinates[1],
      ));
    }
  }

  return { clusters, leaves };
}

/**
 * Zoom level at which a cluster expands into its children. Keeps the
 * supercluster instance encapsulated so map components never touch it.
 */
export function getExpansionZoom(index: HotspotClusterIndex, clusterId: number): number {
  return index.getClusterExpansionZoom(clusterId);
}
