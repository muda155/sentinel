"use client";

// Inline SVG so the panel stays dependency-free; deck.gl and globe.gl are the
// only rendering libraries this app ships.
export default function Sparkline({ counts, width = 300, height = 28 }:
  { counts: number[]; width?: number; height?: number }) {
  const max = Math.max(1, ...counts);
  const barW = counts.length ? width / counts.length : width;
  return (
    <svg width={width} height={height} role="img" aria-label="activity">
      {counts.map((c, i) => {
        const h = Math.max(1, (c / max) * height);
        return (
          <rect key={i} x={i * barW} y={height - h} width={Math.max(1, barW - 1)} height={h}
                fill={c > 0 ? "#60a5fa" : "#1f2937"} />
        );
      })}
    </svg>
  );
}
