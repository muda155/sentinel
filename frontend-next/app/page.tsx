"use client";
import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { HeatmapLayer } from "@deck.gl/aggregation-layers";
import { ScatterplotLayer } from "@deck.gl/layers";
import { CELL_PICK_LAYER_ID } from "@/lib/map-tooltip";
import { api, GridCell, Hotspot } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import HotspotDetail from "@/components/HotspotDetail";
import LanguageToggle from "@/components/LanguageToggle";
import StreamStatusDot from "@/components/StreamStatus";
import { useT } from "@/lib/i18n";
import { useHotspots } from "@/lib/useHotspots";
import { applyFilters, HotspotFilters } from "@/lib/filters";
import { countNew, getLastSeen, isNew } from "@/lib/whatsnew";
import { parseState, serializeState } from "@/lib/url-state";
import { sortHotspots, type TriageSort } from "@/lib/triage";
import { COLOR } from "@/lib/theme";

// SearchBar is centred on THIS container (420px + padding/border = 446 wide),
// and the container shrinks by HotspotDetail's 340px when a hotspot opens. A
// fixed pixel cap cannot track that — a 480px cap cleared the search bar at
// full width but buried the language toggle and legend behind it once the
// panel was open. Capping relative to the container keeps a 12px gutter at
// every width, with or without the panel.
const SIDE_MAX = "calc(50% - 235px)";

const MapView = dynamic(() => import("@/components/MapView"), { ssr: false });
const GlobeView = dynamic(() => import("@/components/GlobeToggle"), { ssr: false });
const SearchBar = dynamic(() => import("@/components/SearchBar"), { ssr: false });
const FilterPanel = dynamic(() => import("@/components/FilterPanel"), { ssr: false });
const Legend = dynamic(() => import("@/components/Legend"), { ssr: false });
const TriageRail = dynamic(() => import("@/components/TriageRail"), { ssr: false });

export default function Page() {
  const { token, user, hydrated, logout } = useAuth();
  const { t } = useT();
  const router = useRouter();
  // Read once, synchronously, so the first paint already reflects the link —
  // initialising to defaults and correcting in an effect would flash the
  // world view before flying to the shared hotspot. Lazy initialiser, so
  // parseState runs on mount only, not on every render.
  const [initial] = useState(() =>
    parseState(typeof window === "undefined" ? "" : window.location.search));
  const [selected, setSelected] = useState<Hotspot | null>(null);
  const [focus, setFocus] = useState<{ lat: number; lon: number } | null>(null);
  const [showHeat, setShowHeat] = useState(initial.heat);
  const [cells, setCells] = useState<GridCell[]>([]);
  const [globe, setGlobe] = useState(initial.globe);
  const [filters, setFilters] = useState<HotspotFilters>(initial.filters);
  const [railOpen, setRailOpen] = useState(initial.rail);
  const [sort, setSort] = useState<TriageSort>(initial.sort);
  const [showEvents, setShowEvents] = useState(false);
  const { hotspots, status, lastEventAt, settled } = useHotspots(token);
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

  const railHotspots = useMemo(() => sortHotspots(filteredHotspots, sort), [filteredHotspots, sort]);

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

  // A shared ?h= link carries only an id; until /hotspots resolves there is no
  // hotspot object to restore, so the URL write-back must not run (a copy made
  // in that gap would silently lose the hotspot). State, not a ref, on purpose:
  // the write-back has to fire only AFTER the restore commit, which a ref flip
  // inside the same commit would not guarantee. Plain loads start true so the
  // common case is never blocked. The gate waits on `settled` — the first
  // fetch's completion, success or failure — not on rows, so a failed /hotspots
  // cannot disable URL sharing for the whole session.
  const [restored, setRestored] = useState(initial.hotspotId == null);
  useEffect(() => {
    // One-shot: without this guard, closing the restored panel would
    // immediately re-open it on the next render.
    if (restored || initial.hotspotId == null || !settled) return;
    setRestored(true);
    const match = hotspots.find((h) => h.hotspot_id === initial.hotspotId);
    if (!match) return;   // stale or unavailable id — leave the map alone rather than erroring
    setSelected(match);
    setFocus({ lat: match.lat, lon: match.lon });
  }, [restored, hotspots, settled, initial.hotspotId]);

  useEffect(() => {
    if (!restored) return;   // wait for the hotspot restore before touching the URL
    if (typeof window === "undefined") return;
    const qs = serializeState({
      hotspotId: selected?.hotspot_id ?? null, filters, heat: showHeat, globe,
      rail: railOpen, sort,
    });
    // replaceState, not router.replace: a Next navigation would re-run the
    // route and remount MapView, throwing away the deck.gl view state on
    // every slider tick.
    window.history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
  }, [restored, selected, filters, showHeat, globe, railOpen, sort]);

  if (!hydrated) {
    return (
      <main style={{ position: "absolute", inset: 0, background: "#0d1117", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <span style={{ color: "#6b7280", fontSize: 14 }}>{t("app.loading")}</span>
      </main>
    );
  }
  if (!token || !user) return null; // redirecting

  const heatLayer = showHeat
    ? [
        new HeatmapLayer<GridCell>({
          id: "convergence-heat", data: cells,
          getPosition: (d) => [d.lon, d.lat],
          getWeight: (d) => d.convergence_score, radiusPixels: 60,
        }),
        // Invisible but pickable: the heatmap texture cannot report which cell
        // the cursor is over. Sits above the heatmap so it wins the pick.
        new ScatterplotLayer<GridCell>({
          id: CELL_PICK_LAYER_ID, data: cells,
          pickable: true, radiusUnits: "pixels",
          getPosition: (d) => [d.lon, d.lat],
          getRadius: 30,
          getFillColor: [0, 0, 0, 0],
        }),
      ]
    : [];

  return (
    <main style={{ position: "absolute", inset: 0, display: "flex" }}>
      <TriageRail
        hotspots={railHotspots}
        sort={sort}
        onSortChange={setSort}
        selectedId={selected?.hotspot_id ?? null}
        onSelect={handleSearchSelect}
        open={railOpen}
        onToggle={() => setRailOpen((o) => !o)}
      />
      <div style={{ position: "relative", flex: 1, minWidth: 0 }}>
        <SearchBar token={token} onSelectHotspot={handleSearchSelect} />
        {globe ? <GlobeView hotspots={filteredHotspots} onSelect={handleSelectHotspot} /> : <MapView onSelect={handleSelectHotspot} extraLayers={heatLayer} hotspots={filteredHotspots} focus={focus} newHotspots={newHotspots} token={token} showEvents={showEvents} timeWindow={filters.timeWindow} />}
        <div style={{ position: "absolute", top: 12, left: 12, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-start", maxWidth: SIDE_MAX }}>
          <label style={{ background: "#111", color: "#eee", padding: "8px 12px", borderRadius: 6, cursor: "pointer" }}>
            <input type="checkbox" checked={showHeat} onChange={(e) => setShowHeat(e.target.checked)} /> {t("header.heatmap")}
          </label>
          <label style={{ background: "#111", color: "#eee", padding: "8px 12px", borderRadius: 6, cursor: "pointer" }}>
            <input type="checkbox" checked={showEvents} disabled={globe} onChange={(e) => setShowEvents(e.target.checked)} /> {t("header.rawEvents")}
          </label>
          <button onClick={() => setGlobe((g) => !g)} style={{ background: "#111", color: "#eee", padding: "8px 12px", borderRadius: 6, border: "none", cursor: "pointer" }}>
            {globe ? "2D Map" : t("header.globe")}
          </button>
          <LanguageToggle />
          <Legend />
          <FilterPanel filters={filters} onChange={setFilters} visible={filteredHotspots.length} total={total} newCount={newCount} />
        </div>
        <div style={{ position: "absolute", top: 12, right: 12, display: "flex", gap: 8, alignItems: "center", maxWidth: SIDE_MAX, background: "#111", padding: "6px 10px", borderRadius: 6 }}>
          <StreamStatusDot status={status} lastEventAt={lastEventAt} />
          <span style={{ color: "#374151" }}>|</span>
          <span style={{ color: "#aaa", fontSize: 12, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{user.username} ({user.role})</span>
          {user.role === "admin" && (
            <Link href="/admin/users" style={{ color: COLOR.link, fontSize: 12, whiteSpace: "nowrap" }}>
              {t("admin.users.short")}
            </Link>
          )}
          <button onClick={logout} style={{ background: "#333", color: "#eee", padding: "6px 12px", borderRadius: 6, border: "none", cursor: "pointer", fontSize: 12, flexShrink: 0 }}>
            {t("header.logout")}
          </button>
        </div>
      </div>
      {selected && <HotspotDetail key={selected.hotspot_id} hotspot={selected} onClose={() => setSelected(null)} />}
    </main>
  );
}
