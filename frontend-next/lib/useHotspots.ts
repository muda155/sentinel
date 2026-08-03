"use client";
import { useEffect, useState } from "react";
import { api, Hotspot } from "@/lib/api";
import { connectHotspotStream } from "@/lib/sse";
import { trailingDebounce } from "@/lib/debounce";
import type { StreamStatus } from "@/lib/stream-status";

export function useHotspots(token: string | null): {
  hotspots: Hotspot[]; status: StreamStatus; lastEventAt: number | null;
} {
  const [hotspots, setHotspots] = useState<Hotspot[]>([]);
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const [lastEventAt, setLastEventAt] = useState<number | null>(null);

  useEffect(() => {
    api.hotspots(token).then(setHotspots).catch(() => setHotspots([]));
  }, [token]);

  useEffect(() => {
    if (!token) return;
    const base = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
    const refetch = () => api.hotspots(token).then(setHotspots).catch(() => {});
    // A pipeline tick re-emits every hotspot; without a debounce that is one
    // /hotspots refetch per SSE event and the 60 req/min limit 429s.
    const debounced = trailingDebounce(refetch, 3000);
    // lastEventAt tracks stream liveness, so it is stamped per raw event —
    // not from the debounced refetch, which would under-report by up to 3s.
    const stamp = (fn: () => void) => (d: unknown) => { void d; setLastEventAt(Date.now()); fn(); };
    const disconnect = connectHotspotStream(base, token, {
      onHotspot: stamp(debounced),
      onSummary: stamp(debounced),
      onStatus: setStatus,
    });
    return () => {
      debounced.cancel();
      disconnect();
    };
  }, [token]);

  return { hotspots, status, lastEventAt };
}
