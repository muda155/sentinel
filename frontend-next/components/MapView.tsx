"use client";
import { useEffect, useRef, useState, useMemo } from "react";
import DeckGL from "@deck.gl/react";
import { ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { FlyToInterpolator, WebMercatorViewport } from "@deck.gl/core";
import { Map } from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import type { EventFeature, Hotspot } from "@/lib/api";
import { fillColor, ringColor } from "@/lib/colors";
import { radiusForConvergence } from "@/lib/marker-size";
import { useT } from "@/lib/i18n";
import { mapTooltip, RAW_EVENT_LAYER_ID, type PickInfo } from "@/lib/map-tooltip";
import { useCluster } from "@/lib/useCluster";
import type { ClusterFeature } from "@/lib/clustering";
import { useRawEvents } from "@/lib/useRawEvents";
import { bboxFromBounds, quantizeBbox, bboxKey, RAW_PAGE_SIZE, type Bbox } from "@/lib/events-layer";
import type { TimeWindow } from "@/lib/filters";

const INITIAL_VIEW = { longitude: 30, latitude: 30, zoom: 2, pitch: 0, bearing: 0 };
const MAP_STYLE = process.env.NEXT_PUBLIC_MAP_STYLE ?? "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
const WORLD_BBOX: [number, number, number, number] = [-180, -90, 180, 90];
const CLUSTER_ZOOM_THRESHOLD = 7;
const FOCUS_ZOOM = 6;
const MAX_CLUSTER_ZOOM = 10; // beyond this, cell-level context is lost

const COUNT_COLOR: [number, number, number, number] = [120, 180, 255, 200];
const COUNT_TEXT_COLOR: [number, number, number, number] = [255, 255, 255, 255];
const CLUSTER_LINE_DEFAULT: [number, number, number, number] = [80, 140, 220, 255];

// FR-13 ring semantics, borrowed for clusters: a cluster hiding a Critical
// hotspot must not look like one holding three Medium ones. Medium has no ring
// in FR-13, so it keeps the neutral outline instead of disappearing.
function clusterLineColor(worst: string): [number, number, number, number] {
  const ring = ringColor(worst);
  return ring[3] === 0 ? CLUSTER_LINE_DEFAULT : ring;
}

export default function MapView({
  hotspots, onSelect, extraLayers = [], focus, newHotspots = [],
  token = null, showEvents = false, timeWindow = "7d",
}: { hotspots: Hotspot[]; onSelect?: (h: Hotspot) => void;
     extraLayers?: unknown[]; focus?: { lat: number; lon: number } | null;
     newHotspots?: Hotspot[]; token?: string | null;
     showEvents?: boolean; timeWindow?: TimeWindow }) {
  const [viewState, setViewState] = useState<Record<string, unknown>>(INITIAL_VIEW);
  const { t } = useT();

  const zoom = Number(viewState.zoom ?? 2);

  const containerRef = useRef<HTMLDivElement>(null);
  const [bbox, setBbox] = useState<Bbox | null>(null);

  // Recompute only while the layer is on; skip entirely when it is off so
  // panning costs nothing extra in the common case.
  useEffect(() => {
    if (!showEvents) { setBbox(null); return; }
    const el = containerRef.current;
    if (!el) return;
    const vp = new WebMercatorViewport({
      ...(viewState as { longitude: number; latitude: number; zoom: number }),
      width: el.clientWidth || 1, height: el.clientHeight || 1,
    });
    const raw = bboxFromBounds(vp.getBounds());
    if (!raw) { setBbox(null); return; }   // dateline wrap — clear, don't keep the old side
    const next = quantizeBbox(raw);
    setBbox((prev) => (prev && bboxKey(prev) === bboxKey(next) ? prev : next));
  }, [showEvents, viewState]);

  const { features: rawEvents, failed } = useRawEvents(token, showEvents, bbox, timeWindow);

  // A full /events page-1 is the oldest-ingested slice of the bbox, not the
  // whole set — the chip is honest about the truncation. `failed` tells an
  // error apart from a genuinely empty viewport. Bottom-left corner, clear of
  // MapLibre's bottom-right attribution.
  const rawHint = showEvents && (failed || rawEvents.length === RAW_PAGE_SIZE) ? (
    <div style={{ position: "absolute", bottom: 12, left: 12, background: "#111", color: failed ? "#f87171" : "#9ca3af", padding: "4px 8px", borderRadius: 4, fontSize: 11, border: "1px solid #262d3a" }}>
      {failed ? t("events.failed") : t("events.truncated").replace("{n}", String(RAW_PAGE_SIZE))}
    </div>
  ) : null;

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

  const rawEventLayer = rawEvents.length > 0
    ? new ScatterplotLayer<EventFeature>({
        id: RAW_EVENT_LAYER_ID,
        data: rawEvents,
        pickable: true,
        radiusUnits: "pixels",
        getPosition: (d) => d.geometry.coordinates,
        getRadius: 2.5,
        // Not [148,163,184,*] — that is FR-13's "low confidence" grey from
        // lib/colors.ts, and a raw point is not a low-confidence hotspot.
        getFillColor: [100, 116, 139, 90],
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
        getLineWidth: (d) => (d.worst_alert === "Medium" ? 1 : 3),
        getLineColor: (d) => clusterLineColor(d.worst_alert),
        updateTriggers: { getLineColor: clusters, getLineWidth: clusters },
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
    getRadius: (d) => radiusForConvergence(d.convergence_score),
    getFillColor: (d) => fillColor(d.conf_score),
    stroked: true,
    lineWidthUnits: "pixels",
    getLineWidth: (d) => (d.alert_level === "Medium" ? 0 : 3),
    getLineColor: (d) => ringColor(d.alert_level),
    onClick: (info) => info.object && onSelect?.(info.object as Hotspot),
    updateTriggers: {
      getFillColor: orderedLeaves, getLineColor: orderedLeaves,
      getRadius: orderedLeaves,
    },
  });

  return (
    <div ref={containerRef} style={{ position: "absolute", inset: 0 }}>
      <DeckGL
        viewState={viewState}
        onViewStateChange={({ viewState: vs }) => setViewState(vs as Record<string, unknown>)}
        getTooltip={(info: PickInfo) => mapTooltip(info, t)}
        controller
        layers={[
          ...(extraLayers as never[]),
          ...(rawEventLayer ? [rawEventLayer] : []),
          ...(highlightLayer ? [highlightLayer] : []),
          ...(clusterLayer ? [clusterLayer] : []),
          ...(clusterTextLayer ? [clusterTextLayer] : []),
          hotspotLayer,
        ]}
      >
        <Map mapStyle={MAP_STYLE} />
      </DeckGL>
      {rawHint}
    </div>
  );
}
