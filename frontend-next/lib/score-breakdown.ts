import type { Claim, Hotspot, HotspotEvent } from "@/lib/api";

// Mirrors pipeline/scoring.py defaults (SENTINEL_CONF_W_DENSITY / _W_DIVERSITY).
// These are env-overridable server-side, which is exactly why every consumer
// below verifies the reconstruction against the published score instead of
// trusting them.
export const CONF_W_DENSITY = 0.7;
export const CONF_W_DIVERSITY = 0.3;

// Reconstruction is exact arithmetic on a float the server already rounded for
// display, so allow half a point before declaring a mismatch.
const RECONSTRUCT_TOLERANCE = 0.51;

export type ConfBreakdown =
  | { mode: "unavailable" }
  | { mode: "raw"; sourceDensity: number; diversity: number }
  | { mode: "weighted"; density: number; diversity: number; sourceDensity: number; rawDiversity: number };

export function confBreakdown(h: Hotspot): ConfBreakdown {
  const d = h.source_density;
  const v = h.geopolitical_diversity;
  if (d == null || v == null) return { mode: "unavailable" };

  const density = CONF_W_DENSITY * d * 100;
  const diversity = CONF_W_DIVERSITY * v * 100;
  if (Math.abs(density + diversity - h.conf_score) > RECONSTRUCT_TOLERANCE) {
    return { mode: "raw", sourceDensity: d, diversity: v };
  }
  return { mode: "weighted", density, diversity, sourceDensity: d, rawDiversity: v };
}

export type ConvergenceBreakdown =
  | { mode: "unavailable" }
  | { mode: "raw"; types: number; events: number }
  | { mode: "split"; typeScore: number; countBoost: number; types: number; events: number; clamped: boolean };

export function convergenceBreakdown(h: Hotspot): ConvergenceBreakdown {
  const types = h.convergence_types;
  const events = h.convergence_events;
  // NULL convergence_score = "never went through grid-cell convergence", NOT a
  // genuine zero. Coalescing it to 0 upstream would make a never-scored
  // hotspot look scored (hollow bar under "convergence 0.0").
  if (h.convergence_score == null) return { mode: "unavailable" };
  if (types == null || events == null) return { mode: "unavailable" };
  // Zero inputs are indistinguishable from "not scored" — drawing an empty
  // split bar under "convergence 0.0" would render a hollow track.
  if (types === 0 && events === 0) return { mode: "unavailable" };

  // pipeline/clustering.py:119
  const typeScore = types * 25;
  const countBoost = Math.min(25, events * 2);
  const total = Math.min(100, typeScore + countBoost);
  if (Math.abs(total - h.convergence_score) > RECONSTRUCT_TOLERANCE) {
    return { mode: "raw", types, events };
  }
  return {
    mode: "split", typeScore, countBoost, types, events,
    clamped: typeScore + countBoost > 100,
  };
}

export type MixEntry = { label: string; count: number };

/** Claim counts by status, disputed first — matches orderClaims' priority. */
export function consistencyMix(claims: Claim[]): MixEntry[] {
  const order: Claim["status"][] = ["disputed", "uncorroborated", "corroborated"];
  return order
    .map((status) => ({ label: status, count: claims.filter((c) => c.status === status).length }))
    .filter((e) => e.count > 0);
}

/**
 * Trust-tier and country spread over UNIQUE DOMAINS.
 *
 * Unique domains, not events: pipeline/scoring.py sums trust over unique
 * domains and reads country_code over unique domains. Counting events instead
 * would let one prolific outlet dominate a chart that claims to explain
 * source_density, and the chart would disagree with the score above it.
 */
export function sourceMix(events: HotspotEvent[]): {
  tiers: MixEntry[];
  countries: MixEntry[];
  uniqueDomains: number;
} {
  const byDomain = new Map<string, HotspotEvent>();
  for (const e of events) if (!byDomain.has(e.domain)) byDomain.set(e.domain, e);
  const rows = [...byDomain.values()];

  const tierCounts = new Map<number, number>();
  const countryCounts = new Map<string, number>();
  for (const r of rows) {
    const tier = r.trust_tier ?? 4;
    tierCounts.set(tier, (tierCounts.get(tier) ?? 0) + 1);
    const cc = r.country_code ?? "??";
    countryCounts.set(cc, (countryCounts.get(cc) ?? 0) + 1);
  }

  return {
    tiers: [...tierCounts.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([tier, count]) => ({ label: String(tier), count })),
    countries: [...countryCounts.entries()]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([label, count]) => ({ label, count })),
    uniqueDomains: rows.length,
  };
}
