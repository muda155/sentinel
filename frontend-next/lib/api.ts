export type Hotspot = {
  hotspot_id: number; lat: number; lon: number;
  conf_score: number; convergence_score: number;
  alert_level: "Critical" | "High" | "Medium"; event_count: number;
};
export type HotspotSummary = {
  summary: string; conflict_detected: boolean; sources_cited: string[];
  conf_score: number; convergence_score: number;
};
export type GridCell = {
  cell_id: string; lat: number; lon: number;
  convergence_score: number; alert_level: string; total_events: number;
};

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

// In Sprint 11 this reads the JWT from the auth context; Sprint 10 sends none.
export function authHeaders(token?: string): HeadersInit {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function getJson<T>(path: string, token?: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: authHeaders(token) });
  if (res.status === 401) throw new Error("unauthorized");
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json() as Promise<T>;
}

export const api = {
  hotspots: (token?: string, limit = 200) =>
    getJson<Hotspot[]>(`/hotspots?limit=${limit}`, token),
  summary: (id: number, token?: string) =>
    getJson<HotspotSummary>(`/hotspots/${id}/summary`, token),
  gridCells: (token?: string, minConvergence = 1) =>
    getJson<GridCell[]>(`/grid_cells?min_convergence=${minConvergence}`, token),
};
