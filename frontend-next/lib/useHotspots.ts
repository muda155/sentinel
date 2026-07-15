"use client";
import { useEffect, useState } from "react";
import { api, Hotspot } from "@/lib/api";
import { connectHotspotStream } from "@/lib/sse";
import { trailingDebounce } from "@/lib/debounce";

export function useHotspots(token: string | null): { hotspots: Hotspot[] } {
  const [hotspots, setHotspots] = useState<Hotspot[]>([]);

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
    const disconnect = connectHotspotStream(base, token, { onHotspot: debounced, onSummary: debounced });
    return () => {
      debounced.cancel();
      disconnect();
    };
  }, [token]);

  return { hotspots };
}
