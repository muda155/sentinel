"use client";
import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { HeatmapLayer } from "@deck.gl/aggregation-layers";
import { api, GridCell, Hotspot } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import HotspotDetail from "@/components/HotspotDetail";
import LanguageToggle from "@/components/LanguageToggle";
import { useT } from "@/lib/i18n";
import { useHotspots } from "@/lib/useHotspots";
import { applyFilters, DEFAULT_FILTERS, HotspotFilters } from "@/lib/filters";
import { countNew, getLastSeen, isNew } from "@/lib/whatsnew";

const MapView = dynamic(() => import("@/components/MapView"), { ssr: false });
const GlobeView = dynamic(() => import("@/components/GlobeToggle"), { ssr: false });
const SearchBar = dynamic(() => import("@/components/SearchBar"), { ssr: false });
const FilterPanel = dynamic(() => import("@/components/FilterPanel"), { ssr: false });
const Legend = dynamic(() => import("@/components/Legend"), { ssr: false });

export default function Page() {
  const { token, user, hydrated, logout } = useAuth();
  const { t } = useT();
  const router = useRouter();
  const [selected, setSelected] = useState<Hotspot | null>(null);
  const [focus, setFocus] = useState<{ lat: number; lon: number } | null>(null);
  const [showHeat, setShowHeat] = useState(false);
  const [cells, setCells] = useState<GridCell[]>([]);
  const [globe, setGlobe] = useState(false);
  const [filters, setFilters] = useState<HotspotFilters>(DEFAULT_FILTERS);
  const { hotspots } = useHotspots(token);
  // Memoize so filteredHotspots keeps a stable reference across unrelated
  // re-renders (e.g. selecting a hotspot), which keeps the cluster index from
  // rebuilding; it recomputes only when hotspots or filters actually change.
  const { filtered: filteredHotspots, total } = useMemo(
    () => applyFilters(hotspots, filters),
    [hotspots, filters],
  );

  const lastSeen = getLastSeen();
  const newCount = countNew(hotspots, lastSeen);
  const newHotspots = useMemo(() => {
    const newIds = new Set(
      hotspots.filter((h) => isNew(h.created_at, lastSeen)).map((h) => h.hotspot_id),
    );
    return filteredHotspots.filter((h) => newIds.has(h.hotspot_id));
  }, [hotspots, filteredHotspots, lastSeen]);

  const handleSearchSelect = (h: Hotspot) => {
    setFocus({ lat: h.lat, lon: h.lon });
    setSelected(h);
  };

  const handleSelectHotspot = (h: Hotspot) => {
    setSelected(h);
  };

  useEffect(() => {
    if (hydrated && token === null) router.push("/login");
  }, [hydrated, token, router]);

  useEffect(() => {
    if (showHeat && cells.length === 0 && token) api.gridCells(token).then(setCells).catch(() => {});
  }, [showHeat, cells.length, token]);

  if (!hydrated) {
    return (
      <main style={{ position: "absolute", inset: 0, background: "#0d1117", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <span style={{ color: "#6b7280", fontSize: 14 }}>{t("app.loading")}</span>
      </main>
    );
  }
  if (!token || !user) return null; // redirecting

  const heatLayer = showHeat
    ? [new HeatmapLayer<GridCell>({
        id: "convergence-heat", data: cells,
        getPosition: (d) => [d.lon, d.lat],
        getWeight: (d) => d.convergence_score, radiusPixels: 60,
      })]
    : [];

  return (
    <main style={{ position: "absolute", inset: 0, display: "flex" }}>
      <div style={{ position: "relative", flex: 1, minWidth: 0 }}>
        <SearchBar token={token} onSelectHotspot={handleSearchSelect} />
        {globe ? <GlobeView hotspots={filteredHotspots} onSelect={handleSelectHotspot} /> : <MapView onSelect={handleSelectHotspot} extraLayers={heatLayer} hotspots={filteredHotspots} focus={focus} newHotspots={newHotspots} />}
        <div style={{ position: "absolute", top: 12, left: 12, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <label style={{ background: "#111", color: "#eee", padding: "8px 12px", borderRadius: 6, cursor: "pointer" }}>
            <input type="checkbox" checked={showHeat} onChange={(e) => setShowHeat(e.target.checked)} /> {t("header.heatmap")}
          </label>
          <button onClick={() => setGlobe((g) => !g)} style={{ background: "#111", color: "#eee", padding: "8px 12px", borderRadius: 6, border: "none", cursor: "pointer" }}>
            {globe ? "2D Map" : t("header.globe")}
          </button>
          <LanguageToggle />
          <Legend />
        </div>
        <div style={{ position: "absolute", top: 12, right: 12 }}>
          <FilterPanel filters={filters} onChange={setFilters} visible={filteredHotspots.length} total={total} newCount={newCount} />
        </div>
        <div style={{ position: "absolute", bottom: 12, right: 12, display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ color: "#aaa", fontSize: 12 }}>{user.username} ({user.role})</span>
          <button onClick={logout} style={{ background: "#333", color: "#eee", padding: "6px 12px", borderRadius: 6, border: "none", cursor: "pointer", fontSize: 12 }}>
            {t("header.logout")}
          </button>
        </div>
      </div>
      {selected && <HotspotDetail hotspot={selected} onClose={() => setSelected(null)} />}
    </main>
  );
}
