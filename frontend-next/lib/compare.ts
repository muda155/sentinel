import type { WindowConsistency } from "@/lib/window-consistency";
import type { WindowMetrics } from "@/lib/window-metrics";

export type Direction = "up" | "down" | "flat" | "none";

export type CompareRow = {
  key: string;
  labelKey: string;
  a: number | null;
  b: number | null;
  delta: number | null;
  direction: Direction;
  /** False when the client could not reproduce the server's published score,
   *  so the row shows movement it cannot vouch for. */
  trusted: boolean;
};

export type ComparisonInput = {
  a: WindowMetrics;
  b: WindowMetrics;
  consistencyA: WindowConsistency;
  consistencyB: WindowConsistency;
  confTrusted: boolean;
  consistencyTrusted: boolean;
};

// Floats that came out of tanh and entropy never land on an exact tie, so a
// bare !== would report every unchanged score as movement.
const EPSILON = 0.005;

function row(key: string, labelKey: string, a: number | null, b: number | null, trusted = true): CompareRow {
  if (a == null || b == null) {
    return { key, labelKey, a, b, delta: null, direction: "none", trusted };
  }
  const delta = b - a;
  const direction: Direction = Math.abs(delta) < EPSILON ? "flat" : delta > 0 ? "up" : "down";
  return { key, labelKey, a, b, delta, direction, trusted };
}

function score(c: WindowConsistency): number | null {
  return c.mode === "score" ? c.score : null;
}

// Whether "more" of a metric is good. Counts, domains and mean tone carry no
// inherent polarity, so they stay neutral instead of painting "more events" as
// a win (or, worse, "max fatalities up" as one).
const UP_IS_GOOD: Record<string, boolean> = { conf: true, consistency: true, fatalities: false };

/** Semantic tone of a delta so the UI can colour it per metric. */
export function deltaTone(key: string, direction: Direction): "good" | "bad" | "neutral" {
  if (direction === "flat" || direction === "none") return "neutral";
  const upIsGood = UP_IS_GOOD[key];
  if (upIsGood == null) return "neutral";
  const good = direction === "up" ? upIsGood : !upIsGood;
  return good ? "good" : "bad";
}

export function buildComparison(input: ComparisonInput): CompareRow[] {
  const { a, b } = input;
  const rows: CompareRow[] = [
    row("conf", "compare.confidence", a.conf, b.conf, input.confTrusted),
    row("events", "compare.events", a.eventCount, b.eventCount),
    row("types", "compare.eventTypes", a.convergence.types, b.convergence.types),
    row("domains", "compare.uniqueDomains", a.uniqueDomains, b.uniqueDomains),
    row("fatalities", "compare.maxFatalities", a.maxFatalities, b.maxFatalities),
    row("tone", "compare.meanTone", a.meanTone, b.meanTone),
  ];

  const ca = score(input.consistencyA);
  const cb = score(input.consistencyB);
  // A one-sided score would render as a delta against nothing.
  if (ca != null && cb != null) {
    rows.push(row("consistency", "compare.consistency", ca, cb, input.consistencyTrusted));
  }
  return rows;
}
