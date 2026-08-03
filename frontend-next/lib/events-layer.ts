import { TIME_WINDOW_HOURS, type TimeWindow } from "@/lib/filters";

export type Bbox = { sw_lat: number; sw_lon: number; ne_lat: number; ne_lon: number };

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** Normalize WebMercatorViewport.getBounds(), which has returned both
 *  [w, s, e, n] and [[w, s], [e, n]] across deck.gl majors. Returns null on
 *  anything unexpected so a bad read skips the fetch rather than sending NaN. */
export function bboxFromBounds(bounds: unknown): Bbox | null {
  if (!Array.isArray(bounds)) return null;
  if (bounds.length === 4 && bounds.every(isNum)) {
    const [w, s, e, n] = bounds as number[];
    return { sw_lat: s, sw_lon: w, ne_lat: n, ne_lon: e };
  }
  if (bounds.length === 2 && Array.isArray(bounds[0]) && Array.isArray(bounds[1])) {
    const [[w, s], [e, n]] = bounds as number[][];
    if ([w, s, e, n].every(isNum)) return { sw_lat: s, sw_lon: w, ne_lat: n, ne_lon: e };
  }
  return null;
}

/** Snap outward to a whole-degree grid.
 *
 *  /events, /hotspots, /search and /grid_cells share ONE 60 req/min token
 *  bucket per client IP (api/ratelimit.py:52). Refetching on every pixel of
 *  pan would 429 the whole app, not just this layer, so the fetch key only
 *  changes when the viewport crosses a degree boundary. */
export function quantizeBbox(b: Bbox, step = 1): Bbox {
  const down = (v: number) => Math.floor(v / step) * step;
  const up = (v: number) => Math.ceil(v / step) * step;
  return {
    sw_lat: Math.max(-90, down(b.sw_lat)),
    sw_lon: Math.max(-180, down(b.sw_lon)),
    ne_lat: Math.min(90, up(b.ne_lat)),
    ne_lon: Math.min(180, up(b.ne_lon)),
  };
}

export function bboxKey(b: Bbox): string {
  return `${b.sw_lat},${b.sw_lon},${b.ne_lat},${b.ne_lon}`;
}

/** The /events endpoint takes an explicit range; reuse the filter window so
 *  the raw layer and the markers describe the same slice of time. */
export function windowRange(window: TimeWindow, now = Date.now()): { start: string; end: string } {
  return {
    start: new Date(now - TIME_WINDOW_HOURS[window] * 3600_000).toISOString(),
    end: new Date(now).toISOString(),
  };
}
