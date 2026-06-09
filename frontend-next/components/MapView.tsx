"use client";
import { useEffect, useState } from "react";
import DeckGL from "@deck.gl/react";
import { ScatterplotLayer } from "@deck.gl/layers";
import { Map } from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import { api, Hotspot } from "@/lib/api";
import { fillColor, ringColor } from "@/lib/colors";

const INITIAL_VIEW = { longitude: 30, latitude: 30, zoom: 2, pitch: 0, bearing: 0 };
const MAP_STYLE = process.env.NEXT_PUBLIC_MAP_STYLE ?? "https://demotiles.maplibre.org/style.json";

export default function MapView({
  onSelect, extraLayers = [],
}: { onSelect?: (h: Hotspot) => void; extraLayers?: unknown[] }) {
  const [hotspots, setHotspots] = useState<Hotspot[]>([]);

  useEffect(() => { api.hotspots().then(setHotspots).catch(() => setHotspots([])); }, []);

  const hotspotLayer = new ScatterplotLayer<Hotspot>({
    id: "hotspots",
    data: hotspots,
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
    updateTriggers: { getFillColor: hotspots, getLineColor: hotspots },
  });

  return (
    <DeckGL initialViewState={INITIAL_VIEW} controller layers={[...(extraLayers as never[]), hotspotLayer]}>
      <Map mapStyle={MAP_STYLE} />
    </DeckGL>
  );
}
