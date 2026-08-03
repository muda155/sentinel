import type { StreamStatus } from "@/lib/stream-status";

// Reconnect backoff: 1s -> 30s, doubling, with +/-500ms jitter (NFR-5 contract).
export function backoffDelay(attempt: number, rng: () => number = Math.random): number {
  const base = Math.min(30000, 1000 * 2 ** attempt);
  const jitter = (rng() - 0.5) * 1000;   // [-500, +500]
  return Math.max(0, base + jitter);
}

export type SSEHandlers = {
  onHotspot?: (data: unknown) => void;
  onSummary?: (data: unknown) => void;
  onStatus?: (status: StreamStatus) => void;
};

// Connects to /hotspots/stream?token=..., auto-reconnecting with backoff.
export function connectHotspotStream(base: string, token: string, handlers: SSEHandlers): () => void {
  let attempt = 0;
  let es: EventSource | null = null;
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const status = (s: StreamStatus) => { if (!stopped) handlers.onStatus?.(s); };

  function open() {
    if (stopped) return;
    status("connecting");
    es = new EventSource(`${base}/hotspots/stream?token=${encodeURIComponent(token)}`);
    // Note: `attempt` is NOT reset here. A server that accepts and immediately
    // drops would otherwise reconnect every ~1s forever instead of backing off.
    es.onopen = () => status("live");
    es.addEventListener("hotspot_created", (e) => {
      attempt = 0; status("live");
      handlers.onHotspot?.(JSON.parse((e as MessageEvent).data));
    });
    es.addEventListener("summary_ready", (e) => {
      attempt = 0; status("live");
      handlers.onSummary?.(JSON.parse((e as MessageEvent).data));
    });
    es.onerror = () => {
      es?.close();
      if (stopped) return;
      status("reconnecting");
      timer = setTimeout(open, backoffDelay(attempt++));
    };
  }
  open();
  return () => { stopped = true; es?.close(); if (timer) clearTimeout(timer); };
}
