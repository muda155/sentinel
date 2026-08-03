import {
  DEFAULT_FILTERS,
  TIME_WINDOW_HOURS,
  type AlertLevel,
  type HotspotFilters,
  type TimeWindow,
} from "@/lib/filters";

export type UrlState = {
  hotspotId: number | null;
  filters: HotspotFilters;
  heat: boolean;
  globe: boolean;
};

const ALL_LEVELS: AlertLevel[] = ["Critical", "High", "Medium"];

export const DEFAULT_URL_STATE: UrlState = {
  hotspotId: null,
  filters: DEFAULT_FILTERS,
  heat: false,
  globe: false,
};

/** Query string for the current state. Defaults are omitted so a shared link
 *  carries only what the sender actually changed. */
export function serializeState(s: UrlState): string {
  const p = new URLSearchParams();
  if (s.hotspotId != null) p.set("h", String(s.hotspotId));
  if (s.filters.minConf !== DEFAULT_FILTERS.minConf) p.set("conf", String(s.filters.minConf));
  if (s.filters.timeWindow !== DEFAULT_FILTERS.timeWindow) p.set("win", s.filters.timeWindow);
  if (s.filters.alertLevels.size !== ALL_LEVELS.length) {
    p.set("alert", ALL_LEVELS.filter((l) => s.filters.alertLevels.has(l)).join(","));
  }
  if (s.heat) p.set("heat", "1");
  if (s.globe) p.set("globe", "1");
  return p.toString();
}

/** Inverse of serializeState. Every field falls back to its default rather
 *  than throwing — a truncated or hand-edited link must still load. */
export function parseState(search: string): UrlState {
  const p = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);

  const rawId = p.get("h");
  const id = rawId == null ? NaN : Number(rawId);
  const hotspotId = Number.isInteger(id) && id > 0 ? id : null;

  const rawConf = p.get("conf");
  const conf = rawConf == null ? NaN : Number(rawConf);
  const minConf = Number.isFinite(conf) && conf >= 0 && conf <= 100 ? conf : DEFAULT_FILTERS.minConf;

  const rawWin = p.get("win");
  const timeWindow = rawWin != null && rawWin in TIME_WINDOW_HOURS
    ? (rawWin as TimeWindow)
    : DEFAULT_FILTERS.timeWindow;

  const rawAlert = p.get("alert");
  // A fresh Set every time: handing back DEFAULT_FILTERS.alertLevels would let
  // FilterPanel mutate the module-level default for the rest of the session.
  const alertLevels = rawAlert == null
    ? new Set<AlertLevel>(ALL_LEVELS)
    : new Set<AlertLevel>(
        rawAlert.split(",").filter((l): l is AlertLevel => (ALL_LEVELS as string[]).includes(l)),
      );

  return {
    hotspotId,
    filters: { minConf, timeWindow, alertLevels },
    heat: p.get("heat") === "1",
    globe: p.get("globe") === "1",
  };
}
