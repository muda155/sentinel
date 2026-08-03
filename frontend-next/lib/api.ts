export type Hotspot = {
  hotspot_id: number; lat: number; lon: number;
  conf_score: number; convergence_score: number;
  alert_level: "Critical" | "High" | "Medium"; event_count: number;
  consistency_score?: number | null;
  name: string | null;
  start_window: string | null;
  end_window: string | null; created_at: string | null;
};
export type HotspotSummary = {
  summary: string; conflict_detected: boolean; sources_cited: string[];
  conf_score: number; convergence_score: number;
};
export type GridCell = {
  cell_id: string; lat: number; lon: number;
  convergence_score: number; alert_level: string; total_events: number;
};
export type Source = {
  source_id: number; domain: string; trust_tier: number;
  country_code: string | null; country_name: string | null;
};

export type HotspotEvent = {
  event_id: number; title: string | null; url: string | null; domain: string;
  source_system: string; event_type_label: string; event_date: string;
  goldstein_scale: number | null; avg_tone: number | null;
  num_sources: number | null; fatalities: number | null;
  duplicate_count: number;
  trust_tier: number | null; trust_score: number; citation_index: number | null;
};

export type SearchEvent = {
  event_id: number; title: string | null; url: string | null; domain: string;
  event_date: string; report_count: number; hotspot: Hotspot;
};
export type SearchSource = {
  source_id: number; domain: string; trust_tier: number | null; hotspots: Hotspot[];
};
export type SearchResults = {
  hotspots: Hotspot[]; events: SearchEvent[]; sources: SearchSource[];
};

export type ClaimEvidence = {
  event_id: number; citation_index: number | null;
  relation: "supports" | "contradicts" | "neutral";
  probability: number | null; domain: string;
};
export type Claim = {
  claim_id: number; claim_text: string;
  status: "corroborated" | "uncorroborated" | "disputed";
  evidence: ClaimEvidence[];
};
export type HotspotClaims = { claims: Claim[]; insufficient_sources: boolean };

export type EventFeature = {
  type: "Feature";
  geometry: { type: "Point"; coordinates: [number, number] };
  properties: {
    event_id: number; event_date: string; cameo_code: string | null;
    country_code: string | null; url: string | null; title: string | null;
  };
};
export type EventFeatureCollection = {
  type: "FeatureCollection"; features: EventFeature[]; next_cursor: number | null;
};

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export function authHeaders(token?: string | null): HeadersInit {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function getJson<T>(path: string, token?: string | null): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: authHeaders(token) });
  if (res.status === 401) throw new Error("unauthorized");
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json() as Promise<T>;
}

async function patchJson<T>(path: string, body: unknown, token?: string | null): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "PATCH",
    headers: { ...authHeaders(token), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.status === 401) throw new Error("unauthorized");
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json() as Promise<T>;
}

export const api = {
  hotspots: (token?: string | null, limit = 200) =>
    getJson<Hotspot[]>(`/hotspots?limit=${limit}`, token),
  summary: (id: number, token?: string | null) =>
    getJson<HotspotSummary>(`/hotspots/${id}/summary`, token),
  gridCells: (token?: string | null, minConvergence = 1) =>
    getJson<GridCell[]>(`/grid_cells?min_convergence=${minConvergence}`, token),
  sources: (token?: string | null) =>
    getJson<Source[]>("/sources", token),
  updateTrustTier: (sourceId: number, trustTier: number, token?: string | null) =>
    patchJson<{ source_id: number; trust_tier: number }>(
      `/sources/${sourceId}`, { trust_tier: trustTier }, token
    ),
  hotspotEvents: (id: number, token?: string | null) =>
    getJson<HotspotEvent[]>(`/hotspots/${id}/events`, token),
  events: (
    p: { sw_lat: number; sw_lon: number; ne_lat: number; ne_lon: number;
         start: string; end: string; pageSize?: number },
    token?: string | null,
  ) =>
    getJson<EventFeatureCollection>(
      `/events?sw_lat=${p.sw_lat}&sw_lon=${p.sw_lon}&ne_lat=${p.ne_lat}&ne_lon=${p.ne_lon}` +
      `&start=${encodeURIComponent(p.start)}&end=${encodeURIComponent(p.end)}` +
      `&page_size=${p.pageSize ?? 1000}`,
      token,
    ),
  search: (q: string, token?: string | null) =>
    getJson<SearchResults>(`/search?q=${encodeURIComponent(q)}`, token),
  hotspotClaims: (id: number, token?: string | null) =>
    getJson<HotspotClaims>(`/hotspots/${id}/claims`, token),
};
