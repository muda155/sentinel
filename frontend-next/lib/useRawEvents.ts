"use client";
import { useEffect, useRef, useState } from "react";
import { api, type EventFeature } from "@/lib/api";
import { bboxKey, windowRange, type Bbox } from "@/lib/events-layer";
import { trailingDebounce } from "@/lib/debounce";
import type { TimeWindow } from "@/lib/filters";

const FETCH_DEBOUNCE_MS = 800;

/** Raw GDELT/ACLED points for the current viewport.
 *
 *  Fetches only while `enabled`, only when the quantized bbox key changes,
 *  and only behind a trailing debounce — /events shares its 60 req/min token
 *  bucket with /hotspots, /search and /grid_cells. */
export function useRawEvents(
  token: string | null, enabled: boolean, bbox: Bbox | null, window: TimeWindow,
): EventFeature[] {
  const [features, setFeatures] = useState<EventFeature[]>([]);
  const lastKey = useRef<string | null>(null);

  useEffect(() => {
    if (!enabled) { setFeatures([]); lastKey.current = null; return; }
    if (!token || !bbox) return;
    const key = `${bboxKey(bbox)}|${window}`;
    if (key === lastKey.current) return;
    lastKey.current = key;

    let cancelled = false;
    const run = () => {
      const { start, end } = windowRange(window);
      api.events({ ...bbox, start, end }, token)
        .then((fc) => { if (!cancelled) setFeatures(fc.features); })
        .catch(() => { if (!cancelled) setFeatures([]); });
    };
    const debounced = trailingDebounce(run, FETCH_DEBOUNCE_MS);
    debounced();
    return () => { cancelled = true; debounced.cancel(); };
  }, [token, enabled, bbox, window]);

  return features;
}
