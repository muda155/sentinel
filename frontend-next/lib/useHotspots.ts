"use client";
import { useEffect, useState } from "react";
import { api, Hotspot } from "@/lib/api";
import { connectHotspotStream } from "@/lib/sse";

export function useHotspots(token: string | null): { hotspots: Hotspot[] } {
  const [hotspots, setHotspots] = useState<Hotspot[]>([]);

  useEffect(() => {
    api.hotspots(token).then(setHotspots).catch(() => setHotspots([]));
  }, [token]);

  useEffect(() => {
    if (!token) return;
    const base = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
    const refetch = () => api.hotspots(token).then(setHotspots).catch(() => {});
    return connectHotspotStream(base, token, { onHotspot: refetch, onSummary: refetch });
  }, [token]);

  return { hotspots };
}
