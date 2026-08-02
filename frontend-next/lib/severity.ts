import type { HotspotEvent } from "@/lib/api";

// GDELT AvgTone is roughly -20..+20 in practice; GoldsteinScale is -10..+10
// where negative is more conflictual. Both are advisory context, not FR-13
// encodings, so they never reuse the alert-level palette.
export function formatTone(n: number | null): string | null {
  return n == null ? null : n.toFixed(1);
}

export function formatIntensity(n: number | null): string | null {
  return n == null ? null : n.toFixed(1);
}

export function maxFatalities(events: Pick<HotspotEvent, "fatalities">[]): number | null {
  const vals = events.map((e) => e.fatalities).filter((v): v is number => v != null);
  return vals.length ? Math.max(...vals) : null;
}

export function meanTone(events: Pick<HotspotEvent, "avg_tone">[]): number | null {
  const vals = events.map((e) => e.avg_tone).filter((v): v is number => v != null);
  if (!vals.length) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}
