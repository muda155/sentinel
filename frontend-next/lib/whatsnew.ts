import type { Hotspot } from "@/lib/api";

export const LAST_SEEN_KEY = "sentinel_hotspots_last_seen";

/**
 * Check if a hotspot is new relative to the last-seen timestamp.
 * Returns false for malformed dates.
 */
export function isNew(createdAt: string, lastSeen: number): boolean {
  const created = new Date(createdAt).getTime();
  if (isNaN(created)) return false;
  return created > lastSeen;
}

/**
 * Count hotspots that are new since lastSeen.
 */
export function countNew(hotspots: Hotspot[], lastSeen: number): number {
  return hotspots.reduce((acc, h) => acc + (isNew(h.created_at, lastSeen) ? 1 : 0), 0);
}

/**
 * Read the last-seen timestamp from localStorage. Returns 0 if unset.
 */
export function getLastSeen(): number {
  if (typeof localStorage === "undefined") return 0;
  const val = localStorage.getItem(LAST_SEEN_KEY);
  return val ? Number(val) : 0;
}

/**
 * Store the current timestamp as the last-seen time.
 */
export function markSeen(): void {
  if (typeof localStorage === "undefined") return;
  localStorage.setItem(LAST_SEEN_KEY, String(Date.now()));
}
