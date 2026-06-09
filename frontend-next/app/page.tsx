"use client";
import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { HeatmapLayer } from "@deck.gl/aggregation-layers";
import { api, GridCell, Hotspot } from "@/lib/api";
import HotspotDetail from "@/components/HotspotDetail";

const MapView = dynamic(() => import("@/components/MapView"), { ssr: false });
const GlobeView = dynamic(() => import("@/components/GlobeToggle"), { ssr: false });

export default function Page() {
  const [selected, setSelected] = useState<Hotspot | null>(null);
  const [showHeat, setShowHeat] = useState(false);
  const [cells, setCells] = useState<GridCell[]>([]);
  const [globe, setGlobe] = useState(false);

  useEffect(() => { if (showHeat && cells.length === 0) api.gridCells().then(setCells).catch(() => {}); }, [showHeat, cells.length]);

  const heatLayer = showHeat
    ? [new HeatmapLayer<GridCell>({
        id: "convergence-heat", data: cells,
        getPosition: (d) => [d.lon, d.lat],
        getWeight: (d) => d.convergence_score, radiusPixels: 60,
      })]
    : [];

  return (
    <main style={{ position: "absolute", inset: 0 }}>
      {globe ? <GlobeView /> : <MapView onSelect={setSelected} extraLayers={heatLayer} />}
      <div style={{ position: "absolute", top: 12, left: 12, display: "flex", gap: 8 }}>
        <label style={{ background: "#111", color: "#eee", padding: "8px 12px", borderRadius: 6, cursor: "pointer" }}>
          <input type="checkbox" checked={showHeat} onChange={(e) => setShowHeat(e.target.checked)} /> Convergence heatmap
        </label>
        <button onClick={() => setGlobe((g) => !g)} style={{ background: "#111", color: "#eee", padding: "8px 12px", borderRadius: 6, border: "none", cursor: "pointer" }}>
          {globe ? "2D Map" : "3D Globe"}
        </button>
      </div>
      {selected && <HotspotDetail hotspot={selected} onClose={() => setSelected(null)} />}
    </main>
  );
}
