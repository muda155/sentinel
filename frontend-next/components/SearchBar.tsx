"use client";
import { useEffect, useRef, useState } from "react";
import { api, Hotspot, SearchResults } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { flattenResults, FlatResult } from "@/lib/flatten-results";

const EMPTY: SearchResults = { hotspots: [], events: [], sources: [] };

export default function SearchBar({ token, onSelectHotspot }: {
  token?: string | null; onSelectHotspot: (h: Hotspot) => void;
}) {
  const { t } = useT();
  const inputRef = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchResults>(EMPTY);
  const [error, setError] = useState(false);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [expanded, setExpanded] = useState<Hotspot[] | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    setExpanded(null);
    if (q.trim().length < 2) { setResults(EMPTY); setOpen(false); return; }
    const handle = setTimeout(() => {
      api.search(q, token)
        .then((r) => { setResults(r); setError(false); setOpen(true); setActive(0); })
        .catch(() => { setError(true); setOpen(true); });
    }, 250);
    return () => clearTimeout(handle);
  }, [q, token]);

  const flat: FlatResult[] = expanded
    ? expanded.map((h) => ({
        group: "hotspots" as const, key: `xh${h.hotspot_id}`,
        label: h.name ?? `Hotspot #${h.hotspot_id}`,
        sublabel: `${h.alert_level} · conf ${h.conf_score.toFixed(0)}`, hotspot: h,
      }))
    : flattenResults(results, t);

  const pick = (item: FlatResult) => {
    if (item.hotspot) {
      onSelectHotspot(item.hotspot);
      setOpen(false); setQ(""); inputRef.current?.blur();
    } else if (item.sourceHotspots) {
      setExpanded(item.sourceHotspots); setActive(0);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { setOpen(false); inputRef.current?.blur(); }
    if (!open || flat.length === 0) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => (a + 1) % flat.length); }
    if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => (a - 1 + flat.length) % flat.length); }
    if (e.key === "Enter") { e.preventDefault(); pick(flat[active]); }
  };

  let lastGroup = "";
  return (
    <div style={{ position: "absolute", top: 12, left: "50%", transform: "translateX(-50%)", width: 420, zIndex: 10 }}>
      <input
        ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKeyDown}
        placeholder={`${t("search.placeholder")} (⌘K)`}
        style={{ width: "100%", padding: "8px 12px", borderRadius: 8, border: "1px solid #333", background: "#111", color: "#eee" }}
      />
      {open && (
        <ul style={{ listStyle: "none", margin: 4, padding: 4, background: "#111", border: "1px solid #333", borderRadius: 8, maxHeight: 360, overflowY: "auto" }}>
          {error && <li style={{ padding: 8, color: "#f87171" }}>{t("search.unavailable")}</li>}
          {!error && flat.length === 0 && <li style={{ padding: 8, color: "#9ca3af" }}>{t("search.noResults")}</li>}
          {!error && flat.map((item, i) => {
            const header = item.group !== lastGroup && !expanded
              ? <div style={{ fontSize: 11, color: "#6b7280", textTransform: "uppercase", padding: "6px 8px 2px" }}>
                  {t(`search.group.${item.group}`)}
                </div>
              : null;
            lastGroup = item.group;
            return (
              <li key={item.key}>
                {header}
                <div onClick={() => pick(item)} onMouseEnter={() => setActive(i)}
                     style={{ padding: "6px 8px", borderRadius: 6, cursor: "pointer",
                              background: i === active ? "#1f2937" : "transparent" }}>
                  <div style={{ color: "#eee" }}>{item.label}</div>
                  <div style={{ fontSize: 11, color: "#9ca3af" }}>{item.sublabel}</div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
