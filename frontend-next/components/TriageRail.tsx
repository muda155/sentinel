"use client";
import { useRef } from "react";
import type { Hotspot } from "@/lib/api";
import { fillColor, ringColor } from "@/lib/colors";
import { useT } from "@/lib/i18n";
import type { MessageKey } from "@/lib/locales/en";
import { TRIAGE_SORTS, TRIAGE_SORT_LABEL, type TriageSort } from "@/lib/triage";

const RAIL_WIDTH = 280;
const RAIL_COLLAPSED = 36;

const rgba = (c: [number, number, number, number]) => `rgba(${c[0]},${c[1]},${c[2]},${c[3] / 255})`;

interface Props {
  hotspots: Hotspot[];
  sort: TriageSort;
  onSortChange: (s: TriageSort) => void;
  selectedId: number | null;
  onSelect: (h: Hotspot) => void;
  open: boolean;
  onToggle: () => void;
}

export default function TriageRail(
  { hotspots, sort, onSortChange, selectedId, onSelect, open, onToggle }: Props,
) {
  const { t } = useT();
  const optionRefs = useRef<(HTMLDivElement | null)[]>([]);

  const focusOption = (i: number) => {
    optionRefs.current[i]?.focus();
    // jsdom does not implement scrollIntoView; guard the method itself.
    optionRefs.current[i]?.scrollIntoView?.({ block: "nearest" });
  };

  // ARIA listbox navigation lives on the container, the single tab stop. With
  // up to 200 rows, Tab-walking every option is unusable. `e.target` tells us
  // which row the keypress is about even though the handler is on the listbox.
  const handleListboxKeyDown = (e: React.KeyboardEvent) => {
    const n = hotspots.length;
    if (n === 0) return;
    const targetIdx = optionRefs.current.indexOf(e.target as HTMLDivElement);
    const activeIdx = document.activeElement
      ? optionRefs.current.indexOf(document.activeElement as HTMLDivElement)
      : -1;
    const from = Math.max(targetIdx, activeIdx);   // -1 → nothing focused yet

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        focusOption(from < 0 ? 0 : Math.min(from + 1, n - 1));
        break;
      case "ArrowUp":
        e.preventDefault();
        focusOption(from < 0 ? 0 : Math.max(from - 1, 0));
        break;
      case "Home":
        e.preventDefault();
        focusOption(0);
        break;
      case "End":
        e.preventDefault();
        focusOption(n - 1);
        break;
      case "Enter":
      case " ":
        e.preventDefault();
        if (from >= 0) onSelect(hotspots[from]);
        break;
      default:
        break;
    }
  };

  if (!open) {
    return (
      <div style={{ width: RAIL_COLLAPSED, flexShrink: 0, background: "#0b0e13", borderRight: "1px solid #1f2430", display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 12, gap: 8 }}>
        <button
          onClick={onToggle}
          aria-expanded={false}
          aria-label={t("triage.expand")}
          style={{ background: "#161b22", color: "#9ca3af", border: "1px solid #262d3a", borderRadius: 6, width: 26, height: 26, cursor: "pointer", fontSize: 14, lineHeight: 1 }}
        >
          ›
        </button>
        <span style={{ color: "#6b7280", fontSize: 11 }}>{hotspots.length}</span>
      </div>
    );
  }

  return (
    <div style={{ width: RAIL_WIDTH, flexShrink: 0, background: "#0b0e13", borderRight: "1px solid #1f2430", display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 12px", borderBottom: "1px solid #1f2430" }}>
        <span style={{ color: "#e5e7eb", fontSize: 13, fontWeight: 600 }}>
          {t("triage.title")} <span style={{ color: "#6b7280", fontWeight: 400 }}>({hotspots.length})</span>
        </span>
        <button
          onClick={onToggle}
          aria-expanded
          aria-label={t("triage.collapse")}
          style={{ background: "#161b22", color: "#9ca3af", border: "1px solid #262d3a", borderRadius: 6, width: 24, height: 24, cursor: "pointer", fontSize: 14, lineHeight: 1 }}
        >
          ‹
        </button>
      </div>

      <label style={{ display: "flex", flexDirection: "column", gap: 4, padding: "8px 12px" }}>
        <span style={{ color: "#6b7280", fontSize: 10, textTransform: "uppercase", letterSpacing: 1 }}>
          {t("triage.sortBy")}
        </span>
        <select
          aria-label={t("triage.sortBy")}
          value={sort}
          onChange={(e) => onSortChange(e.target.value as TriageSort)}
          style={{ background: "#161b22", color: "#ccc", border: "1px solid #262d3a", borderRadius: 4, padding: "4px 6px", fontSize: 12 }}
        >
          {TRIAGE_SORTS.map((s) => (
            <option key={s} value={s}>{t(TRIAGE_SORT_LABEL[s] as MessageKey)}</option>
          ))}
        </select>
      </label>

      {hotspots.length === 0 ? (
        <p style={{ color: "#6b7280", fontSize: 12, padding: "8px 12px", margin: 0 }}>{t("triage.empty")}</p>
      ) : (
        <div
          role="listbox"
          aria-label={t("triage.title")}
          tabIndex={0}
          onKeyDown={handleListboxKeyDown}
          style={{ overflowY: "auto", flex: 1, minHeight: 0 }}
        >
          {hotspots.map((h, i) => {
            const isSel = h.hotspot_id === selectedId;
            const ring = ringColor(h.alert_level);
            return (
              <div
                key={h.hotspot_id}
                role="option"
                tabIndex={-1}
                ref={(el) => { optionRefs.current[i] = el; }}
                aria-selected={isSel}
                onClick={() => onSelect(h)}
                style={{
                  display: "flex", alignItems: "center", gap: 8, cursor: "pointer",
                  padding: "8px 12px", borderBottom: "1px solid #131820",
                  background: isSel ? "#161f2e" : "transparent",
                }}
              >
                <span
                  style={{
                    width: 10, height: 10, borderRadius: "50%", flexShrink: 0,
                    background: rgba(fillColor(h.conf_score)),
                    border: ring[3] === 0 ? "none" : `2px solid ${rgba(ring)}`,
                  }}
                />
                <span style={{ flex: 1, minWidth: 0, color: "#d1d5db", fontSize: 12, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {h.name ?? `#${h.hotspot_id}`}
                </span>
                <span style={{ color: "#6b7280", fontSize: 11, flexShrink: 0 }}>
                  {h.conf_score.toFixed(0)} · {h.event_count}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
