export type Hotspot = {
  hotspot_id: number; lat: number; lon: number;
  conf_score: number; convergence_score: number;
  alert_level: "Critical" | "High" | "Medium"; event_count: number;
  name: string | null;
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
  trust_tier: number | null; trust_score: number; citation_index: number | null;
};

export type SearchEvent = {
  event_id: number; title: string | null; url: string | null; domain: string;
  event_date: string; hotspot: Hotspot;
};
export type SearchSource = {
  source_id: number; domain: string; trust_tier: number | null; hotspots: Hotspot[];
};
export type SearchResults = {
  hotspots: Hotspot[]; events: SearchEvent[]; sources: SearchSource[];
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
  search: (q: string, token?: string | null) =>
    getJson<SearchResults>(`/search?q=${encodeURIComponent(q)}`, token),
};
