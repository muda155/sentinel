"use client";
import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { HeatmapLayer } from "@deck.gl/aggregation-layers";
import { api, GridCell, Hotspot } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import HotspotDetail from "@/components/HotspotDetail";
import LanguageToggle from "@/components/LanguageToggle";
import { useT } from "@/lib/i18n";

const MapView = dynamic(() => import("@/components/MapView"), { ssr: false });
const GlobeView = dynamic(() => import("@/components/GlobeToggle"), { ssr: false });
const SearchBar = dynamic(() => import("@/components/SearchBar"), { ssr: false });

export default function Page() {
  const { token, user, hydrated, logout } = useAuth();
  const { t } = useT();
  const router = useRouter();
  const [selected, setSelected] = useState<Hotspot | null>(null);
  const [focus, setFocus] = useState<{ lat: number; lon: number } | null>(null);
  const [showHeat, setShowHeat] = useState(false);
  const [cells, setCells] = useState<GridCell[]>([]);
  const [globe, setGlobe] = useState(false);

  const handleSearchSelect = (h: Hotspot) => {
    setFocus({ lat: h.lat, lon: h.lon });
    setSelected(h);
  };

  useEffect(() => {
    if (hydrated && token === null) router.push("/login");
  }, [hydrated, token, router]);

  useEffect(() => {
    if (showHeat && cells.length === 0 && token) api.gridCells(token).then(setCells).catch(() => {});
  }, [showHeat, cells.length, token]);

  if (!hydrated) return null; // avoid hydration mismatch
  if (!token || !user) return null; // redirecting

  const heatLayer = showHeat
    ? [new HeatmapLayer<GridCell>({
        id: "convergence-heat", data: cells,
        getPosition: (d) => [d.lon, d.lat],
        getWeight: (d) => d.convergence_score, radiusPixels: 60,
      })]
    : [];

  return (
    <main style={{ position: "absolute", inset: 0 }}>
      <SearchBar token={token} onSelectHotspot={handleSearchSelect} />
      {globe ? <GlobeView /> : <MapView onSelect={setSelected} extraLayers={heatLayer} token={token} focus={focus} />}
      <div style={{ position: "absolute", top: 12, left: 12, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <label style={{ background: "#111", color: "#eee", padding: "8px 12px", borderRadius: 6, cursor: "pointer" }}>
          <input type="checkbox" checked={showHeat} onChange={(e) => setShowHeat(e.target.checked)} /> {t("header.heatmap")}
        </label>
        <button onClick={() => setGlobe((g) => !g)} style={{ background: "#111", color: "#eee", padding: "8px 12px", borderRadius: 6, border: "none", cursor: "pointer" }}>
          {globe ? "2D Map" : t("header.globe")}
        </button>
        <LanguageToggle />
      </div>
      <div style={{ position: "absolute", bottom: 12, right: 12, display: "flex", gap: 8, alignItems: "center" }}>
        <span style={{ color: "#aaa", fontSize: 12 }}>{user.username} ({user.role})</span>
        <button onClick={logout} style={{ background: "#333", color: "#eee", padding: "6px 12px", borderRadius: 6, border: "none", cursor: "pointer", fontSize: 12 }}>
          {t("header.logout")}
        </button>
      </div>
      {selected && <HotspotDetail hotspot={selected} onClose={() => setSelected(null)} />}
    </main>
  );
}
