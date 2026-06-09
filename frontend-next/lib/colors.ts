export type RGBA = [number, number, number, number];

// FR-13: green >70, yellow 40-70 (inclusive), grey <40.
export function fillColor(confScore: number): RGBA {
  if (confScore > 70) return [34, 197, 94, 200];   // green
  if (confScore >= 40) return [234, 179, 8, 200];  // yellow
  return [148, 163, 184, 200];                      // grey
}

// FR-13: red ring = Critical, orange = High, none = Medium.
export function ringColor(alertLevel: string): RGBA {
  if (alertLevel === "Critical") return [220, 38, 38, 255];
  if (alertLevel === "High") return [249, 115, 22, 255];
  return [0, 0, 0, 0];
}
