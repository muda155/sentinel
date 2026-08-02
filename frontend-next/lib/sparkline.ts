import type { HotspotEvent } from "@/lib/api";

// UTC day keys so a bucket does not shift under the viewer's timezone.
function dayKey(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function bucketByDay(
  events: Pick<HotspotEvent, "event_date">[],
  days: number,
  now: Date = new Date(),
): { day: string; count: number }[] {
  const buckets = new Map<string, number>();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setUTCDate(d.getUTCDate() - i);
    buckets.set(dayKey(d), 0);
  }
  for (const e of events) {
    const k = dayKey(new Date(e.event_date));
    if (buckets.has(k)) buckets.set(k, (buckets.get(k) ?? 0) + 1);
  }
  return [...buckets.entries()].map(([day, count]) => ({ day, count }));
}
