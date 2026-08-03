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
 *  bucket with /hotspots, /search and /grid_cells. `failed` distinguishes an
 *  empty layer after an error from a viewport that genuinely has no events. */
export function useRawEvents(
  token: string | null, enabled: boolean, bbox: Bbox | null, timeWindow: TimeWindow,
): { features: EventFeature[]; failed: boolean } {
  const [features, setFeatures] = useState<EventFeature[]>([]);
  const [failed, setFailed] = useState(false);
  const lastKey = useRef<string | null>(null);

  useEffect(() => {
    if (!enabled) return;   // disabled output is derived below — no state to reset
    if (!token || !bbox) return;
    const key = `${bboxKey(bbox)}|${timeWindow}`;
    if (key === lastKey.current) return;
    lastKey.current = key;

    let cancelled = false;
    const run = () => {
      const { start, end } = windowRange(timeWindow);
      api.events({ ...bbox, start, end }, token)
        .then((fc) => {
          if (cancelled) return;
          setFeatures(fc.features);
          setFailed(false);
        })
        .catch(() => {
          if (cancelled) return;
          // Never cache a key whose fetch failed: a transient 429 must not
          // leave the layer silently empty until the viewport changes.
          lastKey.current = null;
          setFeatures([]);
          setFailed(true);
        });
    };
    const debounced = trailingDebounce(run, FETCH_DEBOUNCE_MS);
    debounced();
    return () => { cancelled = true; debounced.cancel(); };
  }, [token, enabled, bbox, timeWindow]);

  // Deriving the disabled output (rather than resetting state in the effect)
  // also lets a quick toggle-off/on reuse the cache instead of refetching.
  return { features: enabled ? features : [], failed: enabled ? failed : false };
}
