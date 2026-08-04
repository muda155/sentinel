import Supercluster from "supercluster";
import type { Hotspot } from "@/lib/api";

export type AlertLevel = "Critical" | "High" | "Medium";

const ALERT_RANK: Record<string, number> = { Medium: 0, High: 1, Critical: 2 };

// Aggregated by supercluster's map/reduce, so a cluster can be triaged
// without expanding it.
interface ClusterProps {
  worst_alert: AlertLevel;
  max_conf: number;
}

// getClusters() returns a discriminated union: cluster features carry
// supercluster's ClusterProperties merged with our ClusterProps, leaves carry
// only HotspotProps. The `cluster: true` flag distinguishes them.
type ClusterOrLeafProps = (Supercluster.ClusterProperties & ClusterProps) | HotspotProps;

function isClusterProps(
  p: ClusterOrLeafProps,
): p is Supercluster.ClusterProperties & ClusterProps {
  return (p as Supercluster.ClusterProperties).cluster === true;
}

export interface ClusterFeature {
  /** Cluster centroid longitude */
  lon: number;
  /** Cluster centroid latitude */
  lat: number;
  /** Number of points in this cluster */
  point_count: number;
  /** Unique cluster id used for expansion */
  cluster_id: number;
  /** Highest alert level among the contained hotspots */
  worst_alert: AlertLevel;
  /** Highest conf_score among the contained hotspots */
  max_conf: number;
}

export interface ClusterResult {
  clusters: ClusterFeature[];
  leaves: Hotspot[];
}

/** A supercluster index over hotspot points. Encapsulates supercluster so
 *  callers stay decoupled from the library. */
export type HotspotClusterIndex = Supercluster<HotspotProps, ClusterProps>;

// Properties stored in supercluster for each hotspot feature.
interface HotspotProps {
  hotspot_id: number;
  conf_score: number;
  consistency_score: number | null;
  convergence_score: number | null;
  alert_level: string;
  event_count: number;
  name: string | null;
  start_window: string | null;
  end_window: string | null;
  created_at: string | null;
}

function toProps(h: Hotspot): HotspotProps {
  return {
    hotspot_id: h.hotspot_id,
    conf_score: h.conf_score,
    consistency_score: h.consistency_score ?? null,
    convergence_score: h.convergence_score,
    alert_level: h.alert_level,
    event_count: h.event_count,
    name: h.name,
    start_window: h.start_window,
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
    start_window: p.start_window,
    end_window: p.end_window,
    created_at: p.created_at,
    consistency_score: p.consistency_score ?? null,
  };
}

/**
 * Create a Supercluster index from hotspots.
 * Configures radius (60px) and maxZoom (12) so clustering activates at world/continent zoom.
 */
export function createClusterIndex(hotspots: Hotspot[]): HotspotClusterIndex {
  const index = new Supercluster<HotspotProps, ClusterProps>({
    radius: 60,
    maxZoom: 12,
    map: (props): ClusterProps => ({
      worst_alert: props.alert_level as AlertLevel,
      max_conf: props.conf_score,
    }),
    reduce: (acc, props) => {
      if (ALERT_RANK[props.worst_alert] > ALERT_RANK[acc.worst_alert]) {
        acc.worst_alert = props.worst_alert;
      }
      if (props.max_conf > acc.max_conf) acc.max_conf = props.max_conf;
    },
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
    const props: ClusterOrLeafProps = feature.properties;
    if (isClusterProps(props)) {
      clusters.push({
        lon: feature.geometry.coordinates[0],
        lat: feature.geometry.coordinates[1],
        point_count: props.point_count,
        cluster_id: props.cluster_id,
        worst_alert: props.worst_alert ?? "Medium",
        max_conf: props.max_conf ?? 0,
      });
    } else {
      leaves.push(fromProps(
        props,
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
