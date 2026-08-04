"use client";
import { COLOR, FONT, RADIUS, SPACE } from "@/lib/theme";

export type BarSegment = { label: string; value: number; color: string };

// Inline SVG so the panel stays dependency-free — deck.gl and globe.gl are the
// only rendering libraries this app ships (same rule as components/Sparkline).
export default function StackedBar({
  segments, max = 100, label, width = 300, height = 14, showLegend = true,
}: {
  segments: BarSegment[];
  max?: number;
  label: string;
  width?: number;
  height?: number;
  showLegend?: boolean;
}) {
  const sum = segments.reduce((a, s) => a + s.value, 0);
  // Scale down rather than overflow the track when the parts exceed the cap
  // (convergence clamps at 100 but 4 types alone already reach it).
  const scale = sum > max ? max / sum : 1;
  let x = 0;

  return (
    <div>
      <svg width={width} height={height} role="img"
           aria-label={`${label}: ${segments.map((s) => `${s.label} ${s.value.toFixed(1)}`).join(", ")}`}>
        <rect x={0} y={0} width={width} height={height} rx={RADIUS.sm} fill={COLOR.surfaceRaised} />
        {segments.map((s) => {
          const w = (s.value * scale / max) * width;
          const seg = <rect key={s.label} x={x} y={0} width={Math.max(0, w)} height={height} fill={s.color} />;
          x += w;
          return seg;
        })}
      </svg>
      {showLegend && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: SPACE.md, marginTop: SPACE.xs }}>
          {segments.map((s) => (
            <span key={s.label} style={{ display: "flex", alignItems: "center", gap: SPACE.xs,
                                         fontSize: FONT.sm, color: COLOR.textMuted }}>
              <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: 2, background: s.color }} />
              {s.label} {s.value.toFixed(1)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
