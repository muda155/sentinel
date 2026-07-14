import { Hotspot } from "@/lib/api";

export type AlertLevel = "Critical" | "High" | "Medium";

export type TimeWindow = "24h" | "3d" | "7d" | "30d";

export const TIME_WINDOW_HOURS: Record<TimeWindow, number> = {
  "24h": 24,
  "3d": 72,
  "7d": 168,
  "30d": 720,
};

/** i18n key per window, rendered by FilterPanel via useT(). */
export const TIME_WINDOW_LABEL: Record<TimeWindow, string> = {
  "24h": "filter.window.24h",
  "3d": "filter.window.3d",
  "7d": "filter.window.7d",
  "30d": "filter.window.30d",
};

export interface HotspotFilters {
  minConf: number;
  alertLevels: Set<AlertLevel>;
  timeWindow: TimeWindow;
}

/** FR-19: default noise floor hides grey (<40) markers on load.
 *  FR-18: all alert levels selected = no constraint (all visible).
 *  Default window is 7d — a clean recent view; 30d is the widest the server serves. */
export const DEFAULT_FILTERS: HotspotFilters = {
  minConf: 40,
  alertLevels: new Set<AlertLevel>(["Critical", "High", "Medium"]),
  timeWindow: "7d",
};

/** Check whether a single hotspot passes all filter criteria. */
export function passesFilter(hotspot: Hotspot, filters: HotspotFilters): boolean {
  if (hotspot.conf_score < filters.minConf) return false;

  if (filters.alertLevels.size > 0 && !filters.alertLevels.has(hotspot.alert_level as AlertLevel)) {
    return false;
  }

  if (!hotspot.end_window) return true; // no temporal info — fail open
  const end = new Date(hotspot.end_window);
  if (isNaN(end.getTime())) return true; // malformed — fail open
  const hours = TIME_WINDOW_HOURS[filters.timeWindow];
  const cutoff = Date.now() - hours * 3600_000;
  if (end.getTime() < cutoff) return false;

  return true;
}

/** Apply filters to a full list, returning the filtered subset and original total. */
export function applyFilters(
  hotspots: Hotspot[],
  filters: HotspotFilters,
): { filtered: Hotspot[]; total: number } {
  return {
    filtered: hotspots.filter((h) => passesFilter(h, filters)),
    total: hotspots.length,
  };
}
