import type { Hotspot } from "@/lib/api";

export type TriageSort = "alert" | "conf" | "convergence" | "events" | "recent";

export const TRIAGE_SORTS: TriageSort[] = ["alert", "conf", "convergence", "events", "recent"];

export const TRIAGE_SORT_LABEL: Record<TriageSort, string> = {
  alert: "triage.sort.alert",
  conf: "triage.sort.conf",
  convergence: "triage.sort.convergence",
  events: "triage.sort.events",
  recent: "triage.sort.recent",
};

const ALERT_RANK: Record<string, number> = { Critical: 0, High: 1, Medium: 2 };

function stamp(value: string | null): number {
  if (!value) return 0;
  const n = new Date(value).getTime();
  return isNaN(n) ? 0 : n;
}

function primary(a: Hotspot, b: Hotspot, sort: TriageSort): number {
  switch (sort) {
    case "alert": return (ALERT_RANK[a.alert_level] ?? 9) - (ALERT_RANK[b.alert_level] ?? 9);
    case "conf": return b.conf_score - a.conf_score;
    // never-scored (null) sorts to the bottom, after any genuine zero
    case "convergence": return (b.convergence_score ?? 0) - (a.convergence_score ?? 0);
    case "events": return b.event_count - a.event_count;
    case "recent": return stamp(b.end_window ?? b.created_at) - stamp(a.end_window ?? a.created_at);
  }
}

/** Sort a copy, never the input — app/page.tsx memoizes on array reference.
 *  The confidence/id tiebreak makes the order total, so rows do not shuffle
 *  under the cursor when an SSE refetch returns the same set in a new order. */
export function sortHotspots(hotspots: Hotspot[], sort: TriageSort): Hotspot[] {
  return [...hotspots].sort(
    (a, b) => primary(a, b, sort) || b.conf_score - a.conf_score || a.hotspot_id - b.hotspot_id,
  );
}
