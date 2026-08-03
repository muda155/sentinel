export const MIN_RADIUS = 6;
export const MAX_RADIUS = 14;

/**
 * Marker radius (pixels) for a hotspot's convergence_score.
 *
 * FR-13 spends fill on conf_score and the ring on alert_level, so radius is
 * the free channel on the 2D map. sqrt so the marker's *area* tracks
 * convergence — scaling the radius linearly would exaggerate high scores.
 */
export function radiusForConvergence(convergence: number): number {
  const c = Number.isFinite(convergence)
    ? Math.max(0, Math.min(100, convergence))
    : 0;
  return MIN_RADIUS + (MAX_RADIUS - MIN_RADIUS) * Math.sqrt(c / 100);
}
