"use client";
import {
  HotspotFilters,
  DEFAULT_FILTERS,
  AlertLevel,
  TimeWindow,
  TIME_WINDOW_LABEL,
} from "@/lib/filters";
import { useT } from "@/lib/i18n";
import type { MessageKey } from "@/lib/locales/en";
import { markSeen } from "@/lib/whatsnew";
import { RING_RED, RING_ORANGE, RING_MEDIUM_SWATCH } from "@/lib/colors";

const TIME_OPTIONS: TimeWindow[] = ["24h", "3d", "7d", "30d"];
const ALERT_LEVELS: AlertLevel[] = ["Critical", "High", "Medium"];

interface Props {
  filters: HotspotFilters;
  onChange: (filters: HotspotFilters) => void;
  onRefresh?: () => void;
  visible: number;
  total: number;
  newCount?: number;
}

export default function FilterPanel({ filters, onChange, visible, total, newCount = 0 }: Props) {
  const { t } = useT();

  const toggleLevel = (level: AlertLevel) => {
    const next = new Set(filters.alertLevels);
    if (next.has(level)) next.delete(level);
    else next.add(level);
    onChange({ ...filters, alertLevels: next });
  };

  const showing = t("filter.showing")
    .replace("{n}", String(visible))
    .replace("{m}", String(total));

  return (
    <div
      style={{
        background: "#0f0f0f",
        border: "1px solid #333",
        borderRadius: 8,
        padding: "10px 14px",
        color: "#ccc",
        fontSize: 13,
        minWidth: 200,
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      {/* Confidence slider */}
      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span style={{ color: "#aaa", fontSize: 11, textTransform: "uppercase", letterSpacing: 1 }}>
          {t("filter.confidence")}: {filters.minConf}
        </span>
        <input
          type="range"
          min={0}
          max={100}
          step={5}
          value={filters.minConf}
          onChange={(e) => onChange({ ...filters, minConf: Number(e.target.value) })}
          style={{ width: "100%", accentColor: "#4ade80" }}
        />
      </label>

      {/* Alert-level checkboxes */}
      <fieldset style={{ border: "none", padding: 0, margin: 0 }}>
        <legend style={{ color: "#aaa", fontSize: 11, textTransform: "uppercase", letterSpacing: 1, marginBottom: 4 }}>
          {t("filter.alertLevel")}
        </legend>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {ALERT_LEVELS.map((level) => {
            const checked = filters.alertLevels.has(level);
            const ringColor = level === "Critical" ? RING_RED : level === "High" ? RING_ORANGE : RING_MEDIUM_SWATCH;
            return (
              <label key={level} style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggleLevel(level)}
                />
                <span style={{ width: 10, height: 10, borderRadius: "50%", border: `2px solid ${ringColor}` }} />
                <span>{level}</span>
              </label>
            );
          })}
        </div>
      </fieldset>

      {/* Time window */}
      <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span style={{ color: "#aaa", fontSize: 11, textTransform: "uppercase", letterSpacing: 1 }}>
          {t("filter.timeWindow")}
        </span>
        <select
          value={filters.timeWindow}
          onChange={(e) => onChange({ ...filters, timeWindow: e.target.value as TimeWindow })}
          style={{
            background: "#1a1a1a", color: "#ccc", border: "1px solid #444",
            borderRadius: 4, padding: "3px 6px", fontSize: 13,
          }}
        >
          {TIME_OPTIONS.map((opt) => (
            <option key={opt} value={opt}>
              {t(TIME_WINDOW_LABEL[opt] as MessageKey)}
            </option>
          ))}
        </select>
      </label>

      {/* Counter */}
      <div style={{ fontSize: 12, color: "#aaa", textAlign: "center" }}>{showing}</div>

      {/* What's-new chip */}
      {newCount > 0 && (
        <div style={{ display: "flex", gap: 6, alignItems: "center", justifyContent: "center" }}>
          <span style={{
            background: "#1e3a5f", color: "#7dd3fc", borderRadius: 10,
            padding: "2px 10px", fontSize: 11, fontWeight: 600,
          }}>
            {t("whatsnew.new").replace("{n}", String(newCount))}
          </span>
          <button
            onClick={() => { markSeen(); onChange({ ...filters }); }}
            style={{
              background: "transparent", color: "#888", border: "1px solid #444",
              borderRadius: 4, padding: "2px 8px", cursor: "pointer", fontSize: 11,
            }}
          >
            {t("whatsnew.markSeen")}
          </button>
        </div>
      )}

      {/* Reset */}
      <button
        onClick={() => onChange(DEFAULT_FILTERS)}
        style={{
          background: "#222", color: "#ccc", border: "1px solid #444",
          borderRadius: 4, padding: "4px 10px", cursor: "pointer", fontSize: 12,
        }}
      >
        {t("filter.reset")}
      </button>
    </div>
  );
}
