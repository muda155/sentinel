import type { CompareRow } from "@/lib/compare";
import type { Window } from "@/lib/window-metrics";

export type ReportCitation = {
  index: number; title: string | null; url: string | null; domain: string;
};

export type ExportPayload = {
  hotspot: string;
  windowA: Window;
  windowB: Window;
  rows: CompareRow[];
  citations: ReportCitation[];
};

function csvCell(value: string): string {
  return /[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

function num(value: number | null): string {
  // An empty cell reads as "no value"; the string "null" reads as data.
  return value == null ? "" : String(Number(value.toFixed(2)));
}

export function toCsv(rows: CompareRow[]): string {
  const head = "metric,window_a,window_b,delta,direction,trusted";
  const body = rows.map((r) =>
    [csvCell(r.key), num(r.a), num(r.b), num(r.delta), r.direction, String(r.trusted)].join(",")
  );
  return [head, ...body].join("\n") + "\n";
}

export function toJson(payload: ExportPayload): string {
  return JSON.stringify(payload, null, 2);
}

function signed(value: number | null): string {
  if (value == null) return "—";
  const n = Number(value.toFixed(2));
  return n > 0 ? `+${n}` : String(n);
}

export function toMarkdown(payload: ExportPayload, narrative: string | null): string {
  const lines = [
    `# ${payload.hotspot}`,
    "",
    `**Window A:** ${payload.windowA.from} to ${payload.windowA.to}`,
    `**Window B:** ${payload.windowB.from} to ${payload.windowB.to}`,
    "",
    "## Narrative",
    "",
    narrative ?? "No narrative report was generated for this window.",
    "",
    "## Metrics",
    "",
    "| Metric | Window A | Window B | Change |",
    "| --- | --- | --- | --- |",
    ...payload.rows.map((r) =>
      `| ${r.key} | ${num(r.a) || "—"} | ${num(r.b) || "—"} | ${signed(r.delta)} |`
    ),
  ];

  if (payload.citations.length > 0) {
    lines.push("", "## Sources", "");
    for (const c of payload.citations) {
      lines.push(`[${c.index}] ${c.title ?? c.domain} — ${c.url ?? c.domain}`);
    }
  }

  const untrusted = payload.rows.filter((r) => !r.trusted).map((r) => r.key);
  if (untrusted.length > 0) {
    lines.push(
      "", "## Caveats", "",
      `Recomputed from source events. These metrics could not be reconciled with the published scores and may reflect server-side configuration this client cannot read: ${untrusted.join(", ")}.`,
    );
  }
  return lines.join("\n") + "\n";
}

export function downloadText(filename: string, mime: string, content: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
