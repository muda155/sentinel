import type { Hotspot, HotspotEvent } from "@/lib/api";
import { CONF_W_DENSITY, CONF_W_DIVERSITY } from "@/lib/score-breakdown";

// pipeline/scoring.py SENTINEL_CONF_DENSITY_DIVISOR. Env-overridable server
// side, which is why confTrusted() checks rather than trusts it.
export const CONF_DENSITY_DIVISOR = 3;

const RECONSTRUCT_TOLERANCE = 0.51;

export type Window = { from: string; to: string };

/** Half-open [from, to): an event on the boundary belongs to exactly one of
 *  two adjacent windows, so a comparison never double-counts it. */
export function eventsInWindow(events: HotspotEvent[], w: Window): HotspotEvent[] {
  const from = Date.parse(w.from);
  const to = Date.parse(w.to);
  return events.filter((e) => {
    const t = Date.parse(e.event_date);
    return t >= from && t < to;
  });
}

function uniqueByDomain(events: HotspotEvent[]): HotspotEvent[] {
  const seen = new Map<string, HotspotEvent>();
  for (const e of events) if (!seen.has(e.domain)) seen.set(e.domain, e);
  return [...seen.values()];
}

export function sourceDensity(events: HotspotEvent[]): number {
  const rows = uniqueByDomain(events);
  if (rows.length === 0) return 0;
  const total = rows.reduce((sum, r) => sum + r.trust_score, 0);
  return Math.tanh(total / CONF_DENSITY_DIVISOR);
}

/** Shannon entropy over the country codes of unique domains, normalised by
 *  log2(distinct countries) — pipeline/scoring.py:geopolitical_diversity. */
export function diversity(events: HotspotEvent[]): number {
  const codes = uniqueByDomain(events)
    .map((r) => r.country_code)
    .filter((c): c is string => !!c && c.trim() !== "")
    .map((c) => c.toUpperCase());
  const distinct = new Set(codes);
  if (distinct.size <= 1) return 0;

  const counts = new Map<string, number>();
  for (const c of codes) counts.set(c, (counts.get(c) ?? 0) + 1);
  let entropy = 0;
  for (const count of counts.values()) {
    const p = count / codes.length;
    entropy -= p * Math.log2(p);
  }
  return entropy / Math.log2(distinct.size);
}

export function confFromEvents(events: HotspotEvent[]): number {
  return (CONF_W_DENSITY * sourceDensity(events) + CONF_W_DIVERSITY * diversity(events)) * 100;
}

/**
 * Does the client's copy of the formula reproduce the server's published score?
 *
 * SENTINEL_CONF_W_DENSITY, _W_DIVERSITY and _DENSITY_DIVISOR are all
 * env-overridable server side and invisible here. A windowed confidence built
 * on stale constants would look like a trend. Recomputing the full range and
 * checking it against conf_score turns that silent drift into a visible
 * "cannot reproduce".
 */
export function confTrusted(allEvents: HotspotEvent[], h: Hotspot): boolean {
  return Math.abs(confFromEvents(allEvents) - h.conf_score) <= RECONSTRUCT_TOLERANCE;
}

export type WindowConvergence =
  | { mode: "score"; score: number; types: number; events: number }
  | { mode: "typesOnly"; types: number; events: number };

export type WindowMetrics = {
  eventCount: number;
  uniqueDomains: number;
  maxFatalities: number | null;
  meanTone: number | null;
  sourceDensity: number;
  diversity: number;
  conf: number;
  convergence: WindowConvergence;
};

export function windowMetrics(events: HotspotEvent[], w: Window): WindowMetrics {
  const rows = eventsInWindow(events, w);
  const fatalities = rows.map((r) => r.fatalities).filter((f): f is number => f != null);
  const tones = rows.map((r) => r.avg_tone).filter((t): t is number => t != null);
  const types = new Set(rows.map((r) => r.event_type_label)).size;

  return {
    eventCount: rows.length,
    uniqueDomains: uniqueByDomain(rows).length,
    maxFatalities: fatalities.length ? Math.max(...fatalities) : null,
    meanTone: tones.length ? tones.reduce((a, b) => a + b, 0) / tones.length : null,
    sourceDensity: sourceDensity(rows),
    diversity: diversity(rows),
    conf: confFromEvents(rows),
    // The published convergence_score is computed per GRID CELL over that
    // cell's events (pipeline/clustering.py), not over a hotspot's linked
    // events, so a hotspot-local recomputation is a different quantity. It
    // reports the inputs and refuses to print a score that cannot be
    // reconciled with the one in the panel.
    convergence: { mode: "typesOnly", types, events: rows.length },
  };
}
