// FR-13 on globe.gl: points have no stroke, so alert_level maps to
// altitude + radius; conf_score stays on pointColor via lib/colors.fillColor.
export function pointAltitude(alertLevel: string): number {
  if (alertLevel === "Critical") return 0.06;
  if (alertLevel === "High") return 0.03;
  return 0.01;
}

export function pointRadius(alertLevel: string): number {
  if (alertLevel === "Critical") return 0.6;
  if (alertLevel === "High") return 0.45;
  return 0.3;
}
