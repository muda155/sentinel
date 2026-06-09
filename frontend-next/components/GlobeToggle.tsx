"use client";
import { useEffect, useRef } from "react";
import Globe from "globe.gl";
import { api, Hotspot } from "@/lib/api";
import { fillColor } from "@/lib/colors";

export default function GlobeView() {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const g = new Globe(el).globeImageUrl("//unpkg.com/three-globe/example/img/earth-night.jpg");
    api.hotspots().then((hs: Hotspot[]) => {
      g.pointsData(hs)
        .pointLat("lat").pointLng("lon").pointAltitude(0.02)
        .pointColor((d) => { const [r, gr, b] = fillColor((d as Hotspot).conf_score); return `rgb(${r},${gr},${b})`; });
    });
    return () => { el.innerHTML = ""; };
  }, []);
  return <div ref={ref} style={{ position: "absolute", inset: 0 }} />;
}
