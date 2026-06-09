// Reconnect backoff: 1s -> 30s, doubling, with +/-500ms jitter (NFR-5 contract).
export function backoffDelay(attempt: number, rng: () => number = Math.random): number {
  const base = Math.min(30000, 1000 * 2 ** attempt);
  const jitter = (rng() - 0.5) * 1000;   // [-500, +500]
  return Math.max(0, base + jitter);
}

export type SSEHandlers = {
  onHotspot?: (data: unknown) => void;
  onSummary?: (data: unknown) => void;
};

// Connects to /hotspots/stream?token=..., auto-reconnecting with backoff.
export function connectHotspotStream(base: string, token: string, handlers: SSEHandlers): () => void {
  let attempt = 0;
  let es: EventSource | null = null;
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;

  function open() {
    if (stopped) return;
    es = new EventSource(`${base}/hotspots/stream?token=${encodeURIComponent(token)}`);
    es.addEventListener("hotspot_created", (e) => { attempt = 0; handlers.onHotspot?.(JSON.parse((e as MessageEvent).data)); });
    es.addEventListener("summary_ready", (e) => { attempt = 0; handlers.onSummary?.(JSON.parse((e as MessageEvent).data)); });
    es.onerror = () => {
      es?.close();
      if (stopped) return;
      timer = setTimeout(open, backoffDelay(attempt++));
    };
  }
  open();
  return () => { stopped = true; es?.close(); if (timer) clearTimeout(timer); };
}
