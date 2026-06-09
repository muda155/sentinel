"use client";
import { useEffect, useRef } from "react";
import Globe from "globe.gl";
import { api, Hotspot } from "@/lib/api";
import { fillColor } from "@/lib/colors";

export default function GlobeView() {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const g = new Globe(ref.current).globeImageUrl("//unpkg.com/three-globe/example/img/earth-night.jpg");
    api.hotspots().then((hs: Hotspot[]) => {
      g.pointsData(hs)
        .pointLat("lat").pointLng("lon").pointAltitude(0.02)
        .pointColor((d) => { const [r, gr, b] = fillColor((d as Hotspot).conf_score); return `rgb(${r},${gr},${b})`; });
    });
    return () => { if (ref.current) ref.current.innerHTML = ""; };
  }, []);
  return <div ref={ref} style={{ position: "absolute", inset: 0 }} />;
}
