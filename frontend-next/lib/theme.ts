// Chrome palette only: surfaces, text, borders, and states.
//
// FR-13 ENCODING COLOUR DOES NOT BELONG HERE. Marker fill (conf_score) and
// ring (alert_level) live in lib/colors.ts and nowhere else — a second copy
// would let the map, the legend and the triage rail drift apart. __tests__/
// theme.test.ts fails the build if any value below matches one of them.
export const COLOR = {
  bg: "#0d1117",
  surface: "#111318",
  surfaceRaised: "#1b1f27",
  surfaceSunken: "#0b0e13",
  border: "#2a2f3a",
  borderStrong: "#3a4150",
  text: "#e6edf3",
  textMuted: "#9ca3af",
  textDim: "#6b7280",
  link: "#93c5fd",
  accent: "#60a5fa",
  accentAlt: "#a78bfa",
  danger: "#f87171",
  dangerSurface: "#7f1d1d",
  dangerText: "#fecaca",
  ok: "#34d399",
} as const;

export const SPACE = { xs: 4, sm: 6, md: 8, lg: 12, xl: 16 } as const;
export const RADIUS = { sm: 4, md: 6, lg: 8 } as const;
export const FONT = { xs: 10, sm: 11, base: 12, md: 13, lg: 15, xl: 20 } as const;

import type { CSSProperties } from "react";

export const panelSurface: CSSProperties = {
  background: COLOR.surface,
  color: COLOR.text,
  border: `1px solid ${COLOR.border}`,
  borderRadius: RADIUS.lg,
};

export const chipStyle: CSSProperties = {
  fontSize: FONT.xs,
  padding: "1px 6px",
  borderRadius: RADIUS.sm,
  background: COLOR.surfaceRaised,
  color: COLOR.textMuted,
};

export const buttonStyle: CSSProperties = {
  background: COLOR.surfaceRaised,
  color: COLOR.text,
  padding: `${SPACE.md}px ${SPACE.lg}px`,
  borderRadius: RADIUS.md,
  border: `1px solid ${COLOR.border}`,
  cursor: "pointer",
  fontSize: FONT.md,
};

export const inputStyle: CSSProperties = {
  padding: SPACE.md,
  borderRadius: RADIUS.sm,
  border: `1px solid ${COLOR.border}`,
  background: COLOR.surfaceSunken,
  color: COLOR.text,
  fontSize: FONT.md,
};
