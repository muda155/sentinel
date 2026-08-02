"use client";
import { useEffect, useRef, useState } from "react";
import Globe, { type GlobeInstance } from "globe.gl";
import type { Hotspot } from "@/lib/api";
import { fillColor } from "@/lib/colors";
import { pointAltitude, pointRadius } from "@/lib/globe-encoding";
import { useT } from "@/lib/i18n";

export default function GlobeView({ hotspots, onSelect }: { hotspots: Hotspot[]; onSelect?: (h: Hotspot) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<GlobeInstance | null>(null);
  const { t } = useT();
  const [webglOk] = useState(() => {
    const c = document.createElement("canvas");
    return Boolean(c.getContext("webgl2") || c.getContext("webgl"));
  });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const g = new Globe(el).globeImageUrl("/textures/earth-night.jpg");
    g.pointLat("lat")
      .pointLng("lon")
      .pointAltitude((d) => pointAltitude((d as Hotspot).alert_level))
      .pointRadius((d) => pointRadius((d as Hotspot).alert_level))
      .pointColor((d) => {
        const [r, gr, b] = fillColor((d as Hotspot).conf_score);
        return `rgb(${r},${gr},${b})`;
      })
      .onPointClick((d) => onSelect?.(d as Hotspot));
    instanceRef.current = g;
    return () => {
      const inst = instanceRef.current;
      if (inst) {
        inst.pauseAnimation();
        inst.controls().dispose();
        const r = inst.renderer();
        r.dispose();
        r.forceContextLoss();
        instanceRef.current = null;
      }
      // dispose GL context before removing the canvas — browsers cap live contexts
      el.innerHTML = "";
    };
  }, []);

  useEffect(() => {
    instanceRef.current?.pointsData(hotspots);
  }, [hotspots]);

  if (!webglOk) {
    return (
      <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "#6b7280", fontSize: 14 }}>
        {t("globe.unavailable")}
      </div>
    );
  }

  return <div ref={ref} style={{ position: "absolute", inset: 0 }} />;
}
