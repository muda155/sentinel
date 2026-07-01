"use client";
import { useEffect, useState } from "react";
import DeckGL from "@deck.gl/react";
import { ScatterplotLayer } from "@deck.gl/layers";
import { FlyToInterpolator } from "@deck.gl/core";
import { Map } from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import { Hotspot } from "@/lib/api";
import { fillColor, ringColor } from "@/lib/colors";

const INITIAL_VIEW = { longitude: 30, latitude: 30, zoom: 2, pitch: 0, bearing: 0 };
const MAP_STYLE = process.env.NEXT_PUBLIC_MAP_STYLE ?? "https://demotiles.maplibre.org/style.json";

export default function MapView({
  hotspots, onSelect, extraLayers = [], focus,
}: { hotspots: Hotspot[]; onSelect?: (h: Hotspot) => void;
     extraLayers?: unknown[]; focus?: { lat: number; lon: number } | null }) {
  const [viewState, setViewState] = useState<Record<string, unknown>>(INITIAL_VIEW);

  useEffect(() => {
    if (!focus) return;
    setViewState((vs) => ({
      ...vs, longitude: focus.lon, latitude: focus.lat, zoom: 6,
      transitionDuration: 1200, transitionInterpolator: new FlyToInterpolator(),
    }));
  }, [focus]);

  // Render highest-confidence markers last so they paint on top of lower-score
  // ones when hotspots overlap (green > yellow > grey z-order).
  const orderedHotspots = [...hotspots].sort((a, b) => a.conf_score - b.conf_score);

  const hotspotLayer = new ScatterplotLayer<Hotspot>({
    id: "hotspots",
    data: orderedHotspots,
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
    updateTriggers: { getFillColor: orderedHotspots, getLineColor: orderedHotspots },
  });

  return (
    <DeckGL
      viewState={viewState}
      onViewStateChange={({ viewState: vs }) => setViewState(vs as Record<string, unknown>)}
      controller
      layers={[...(extraLayers as never[]), hotspotLayer]}
    >
      <Map mapStyle={MAP_STYLE} />
    </DeckGL>
  );
}
