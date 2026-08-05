"use client";
import { COLOR, FONT, RADIUS, SPACE } from "@/lib/theme";
import type { MixEntry } from "@/lib/score-breakdown";

// A labelled proportional row list. Used for trust tiers and source countries,
// where the category count is open-ended and a stacked bar would give each
// slice no room for its own label.
export default function MixBars({ entries, title, colorFor }: {
  entries: MixEntry[];
  title: string;
  colorFor?: (label: string) => string;
}) {
  if (entries.length === 0) return null;
  const max = Math.max(...entries.map((e) => e.count));
  return (
    <div style={{ marginBottom: SPACE.lg }}>
      <div style={{ fontSize: FONT.sm, color: COLOR.textMuted, marginBottom: SPACE.xs }}>{title}</div>
      {entries.map((e) => (
        <div key={e.label} style={{ display: "flex", alignItems: "center", gap: SPACE.md, marginBottom: 2 }}>
          <span style={{ fontSize: FONT.sm, color: COLOR.textMuted, width: 64, flexShrink: 0,
                         overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {e.label}
          </span>
          <div style={{ flex: 1, height: 8, background: COLOR.surfaceRaised, borderRadius: RADIUS.sm }}>
            <div style={{ width: `${(e.count / max) * 100}%`, height: "100%",
                          background: colorFor?.(e.label) ?? COLOR.accent, borderRadius: RADIUS.sm }} />
          </div>
          <span style={{ fontSize: FONT.sm, color: COLOR.textDim, width: 20, textAlign: "right" }}>
            {e.count}
          </span>
        </div>
      ))}
    </div>
  );
}
