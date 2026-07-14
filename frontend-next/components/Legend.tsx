"use client";
import { useState } from "react";
import { useT } from "@/lib/i18n";
import { FILL_GREEN, FILL_YELLOW, FILL_GREY, RING_RED, RING_ORANGE, RING_MEDIUM_SWATCH } from "@/lib/colors";

const sectionLabel = {
  color: "#aaa", fontSize: 11, textTransform: "uppercase", letterSpacing: 1,
} as const;

export default function Legend() {
  const { t } = useT();
  const [open, setOpen] = useState(false);

  const fillRow = (color: string, label: string) => (
    <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, lineHeight: 1.6 }}>
      <span style={{ width: 10, height: 10, borderRadius: "50%", background: color }} />
      {label}
    </div>
  );

  const ringRow = (color: string, label: string) => (
    <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, lineHeight: 1.6 }}>
      <span style={{ width: 10, height: 10, borderRadius: "50%", border: `2px solid ${color}`, background: "transparent" }} />
      {label}
    </div>
  );

  return (
    <div
      style={{ position: "relative", display: "inline-flex" }}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        aria-label={t("legend.title")}
        aria-expanded={open}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        style={{
          width: 34, height: 34, borderRadius: "50%", border: "none",
          background: "#111", color: "#eee", cursor: "help",
          fontSize: 16, fontWeight: 700, lineHeight: 1,
        }}
      >
        ?
      </button>

      {open && (
        <div
          role="tooltip"
          style={{
            position: "absolute", top: "calc(100% + 6px)", left: 0, zIndex: 20,
            background: "#0f0f0f", border: "1px solid #333", borderRadius: 8,
            padding: "8px 12px", color: "#ccc", fontSize: 13,
            display: "flex", flexDirection: "column", gap: 4, width: 200,
            boxShadow: "0 4px 16px rgba(0,0,0,0.5)",
          }}
        >
          <div style={{ ...sectionLabel, marginBottom: 2 }}>{t("legend.fill")}</div>
          {fillRow(FILL_GREEN, t("legend.highConfidence"))}
          {fillRow(FILL_YELLOW, t("legend.mediumConfidence"))}
          {fillRow(FILL_GREY, t("legend.lowConfidence"))}
          <div style={{ ...sectionLabel, marginTop: 6, marginBottom: 2 }}>{t("legend.ring")}</div>
          {ringRow(RING_RED, t("legend.criticalAlert"))}
          {ringRow(RING_ORANGE, t("legend.highAlert"))}
          {ringRow(RING_MEDIUM_SWATCH, t("legend.mediumAlert"))}
        </div>
      )}
    </div>
  );
}
