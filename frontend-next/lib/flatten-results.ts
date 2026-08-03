import type { Hotspot, SearchResults } from "@/lib/api";

export type FlatResult = {
  group: "hotspots" | "events" | "sources";
  key: string;
  label: string;
  sublabel: string;
  hotspot?: Hotspot;
  sourceHotspots?: Hotspot[];
};

export function flattenResults(res: SearchResults): FlatResult[] {
  const flat: FlatResult[] = [];
  for (const h of res.hotspots) {
    flat.push({ group: "hotspots", key: `h${h.hotspot_id}`,
                label: h.name ?? `Hotspot #${h.hotspot_id}`,
                sublabel: `${h.alert_level} · conf ${h.conf_score.toFixed(0)}`,
                hotspot: h });
  }
  for (const e of res.events) {
    const dest = e.hotspot.name ?? `#${e.hotspot.hotspot_id}`;
    const reports = e.report_count > 1 ? ` · ${e.report_count} reports` : "";
    flat.push({ group: "events", key: `e${e.event_id}`,
                label: e.title || e.domain,
                sublabel: `${e.domain} · ${dest}${reports}`,
                hotspot: e.hotspot });
  }
  for (const s of res.sources) {
    flat.push({ group: "sources", key: `s${s.source_id}`,
                label: s.domain,
                sublabel: `${s.hotspots.length} hotspots`,
                sourceHotspots: s.hotspots });
  }
  return flat;
}
