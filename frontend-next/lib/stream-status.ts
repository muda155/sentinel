/** Connection state of the hotspot SSE stream.
 *
 *  Deliberately reflects the socket only. Staleness is NOT folded in here:
 *  a healthy pipeline with nothing new to report emits no events for
 *  SENTINEL_POLL_INTERVAL_S (default 900s), so a staleness-driven status
 *  would flag a working system as broken. Elapsed time is surfaced as text.
 */
export type StreamStatus = "connecting" | "live" | "reconnecting";

export const STATUS_COLOR: Record<StreamStatus, string> = {
  connecting: "#9ca3af",
  live: "#22d3ee",
  reconnecting: "#f59e0b",
};

export const STATUS_LABEL: Record<StreamStatus, string> = {
  connecting: "stream.connecting",
  live: "stream.live",
  reconnecting: "stream.reconnecting",
};

/** Coarse duration label: 0s, 12s, 3m, 5h, 2d. */
export function relativeAge(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}
