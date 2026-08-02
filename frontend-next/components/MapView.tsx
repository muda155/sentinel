"use client";
import { useEffect, useState, useMemo } from "react";
import DeckGL from "@deck.gl/react";
import { ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { FlyToInterpolator } from "@deck.gl/core";
import { Map } from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Hotspot } from "@/lib/api";
import { fillColor, ringColor } from "@/lib/colors";
import { useCluster } from "@/lib/useCluster";
import type { ClusterFeature } from "@/lib/clustering";

const INITIAL_VIEW = { longitude: 30, latitude: 30, zoom: 2, pitch: 0, bearing: 0 };
const MAP_STYLE = process.env.NEXT_PUBLIC_MAP_STYLE ?? "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
const WORLD_BBOX: [number, number, number, number] = [-180, -90, 180, 90];
const CLUSTER_ZOOM_THRESHOLD = 7;
const FOCUS_ZOOM = 6;
const MAX_CLUSTER_ZOOM = 10; // beyond this, cell-level context is lost

const COUNT_COLOR: [number, number, number, number] = [120, 180, 255, 200];
const COUNT_TEXT_COLOR: [number, number, number, number] = [255, 255, 255, 255];

export default function MapView({
  hotspots, onSelect, extraLayers = [], focus, newHotspots = [],
}: { hotspots: Hotspot[]; onSelect?: (h: Hotspot) => void;
     extraLayers?: unknown[]; focus?: { lat: number; lon: number } | null;
     newHotspots?: Hotspot[] }) {
  const [viewState, setViewState] = useState<Record<string, unknown>>(INITIAL_VIEW);

  const zoom = Number(viewState.zoom ?? 2);

  const { clusters, leaves, getExpansionZoom } = useCluster(hotspots, WORLD_BBOX, zoom);

  useEffect(() => {
    if (!focus) return;
    setViewState((vs) => ({
      ...vs, longitude: focus.lon, latitude: focus.lat, zoom: FOCUS_ZOOM,
      transitionDuration: 1200, transitionInterpolator: new FlyToInterpolator(),
    }));
  }, [focus]);

  const clusterRadius = (c: ClusterFeature) => Math.min(14 + Math.log2(c.point_count) * 6, 40);

  const highlightLayer = newHotspots.length > 0
    ? new ScatterplotLayer<Hotspot>({
        id: "new-hotspot-highlight",
        data: newHotspots,
        pickable: false,
        radiusUnits: "pixels",
        getPosition: (d) => [d.lon, d.lat],
        getRadius: 16,
        getFillColor: [120, 200, 255, 60],
        stroked: true,
        lineWidthUnits: "pixels",
        getLineWidth: 2,
        getLineColor: [120, 200, 255, 120],
      })
    : null;

  // Render highest-confidence markers last so they paint on top of lower-score
  // ones when hotspots overlap (green > yellow > grey z-order).
  const orderedLeaves = useMemo(
    () => [...leaves].sort((a, b) => a.conf_score - b.conf_score),
    [leaves],
  );

  const handleClusterClick = (info: { object?: ClusterFeature }) => {
    if (!info.object) return;
    const { cluster_id, lon, lat } = info.object;
    const expansionZoom = getExpansionZoom(cluster_id);
    setViewState((vs) => ({
      ...vs,
      longitude: lon,
      latitude: lat,
      zoom: Math.min(expansionZoom + 1, MAX_CLUSTER_ZOOM),
      transitionDuration: 800,
      transitionInterpolator: new FlyToInterpolator(),
    }));
  };

  const clusterLayer = zoom < CLUSTER_ZOOM_THRESHOLD && clusters.length > 0
    ? new ScatterplotLayer<ClusterFeature>({
        id: "clusters",
        data: clusters,
        pickable: true,
        radiusUnits: "pixels",
        getPosition: (d) => [d.lon, d.lat],
        getRadius: clusterRadius,
        getFillColor: COUNT_COLOR,
        stroked: true,
        lineWidthUnits: "pixels",
        getLineWidth: 1,
        getLineColor: [80, 140, 220, 255],
        onClick: handleClusterClick,
      })
    : null;

  const clusterTextLayer = zoom < CLUSTER_ZOOM_THRESHOLD && clusters.length > 0
    ? new TextLayer<ClusterFeature>({
        id: "cluster-counts",
        data: clusters,
        getPosition: (d) => [d.lon, d.lat],
        getText: (d) => String(d.point_count),
        getSize: 12,
        getColor: COUNT_TEXT_COLOR,
        getTextAnchor: "middle",
        getAlignmentBaseline: "center",
        sizeUnits: "pixels",
      })
    : null;

  const hotspotLayer = new ScatterplotLayer<Hotspot>({
    id: "hotspots",
    data: orderedLeaves,
    pickable: true,
    radiusUnits: "pixels",
    getPosition: (d) => [d.lon, d.lat],
    getRadius: 8,
    getFillColor: (d) => fillColor(d.conf_score),
    stroked: true,
    lineWidthUnits: "pixels",
    getLineWidth: (d) => (d.alert_level === "Medium" ? 0 : 3),
    getLineColor: (d) => ringColor(d.alert_level),
    onClick: (info) => info.object && onSelect?.(info.object as Hotspot),
    updateTriggers: { getFillColor: orderedLeaves, getLineColor: orderedLeaves },
  });

  return (
    <DeckGL
      viewState={viewState}
      onViewStateChange={({ viewState: vs }) => setViewState(vs as Record<string, unknown>)}
      controller
      layers={[
        ...(extraLayers as never[]),
        ...(highlightLayer ? [highlightLayer] : []),
        ...(clusterLayer ? [clusterLayer] : []),
        ...(clusterTextLayer ? [clusterTextLayer] : []),
        hotspotLayer,
      ]}
    >
      <Map mapStyle={MAP_STYLE} />
    </DeckGL>
  );
}
