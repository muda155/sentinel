export type Part = { type: "text"; text: string } | { type: "cite"; n: number };

// Splits a SITREP into text + [N] citation tokens for inline rendering (FR-11).
export function parseCitations(summary: string): Part[] {
  const parts: Part[] = [];
  const re = /\[(\d+)\]/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(summary)) !== null) {
    if (m.index > last) parts.push({ type: "text", text: summary.slice(last, m.index) });
    parts.push({ type: "cite", n: parseInt(m[1], 10) });
    last = m.index + m[0].length;
  }
  if (last < summary.length) parts.push({ type: "text", text: summary.slice(last) });
  return parts;
}
