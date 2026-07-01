"use client";
import { useT } from "@/lib/i18n";

export default function Legend() {
  const { t } = useT();

  const row = (color: string, label: string) => (
    <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, lineHeight: 1.6 }}>
      <span style={{ width: 10, height: 10, borderRadius: "50%", background: color }} />
      {label}
    </div>
  );

  return (
    <div
      style={{
        background: "#0f0f0f",
        border: "1px solid #333",
        borderRadius: 8,
        padding: "8px 12px",
        color: "#ccc",
        fontSize: 13,
        display: "flex",
        flexDirection: "column",
        gap: 4,
      }}
    >
      <div style={{ color: "#aaa", fontSize: 11, textTransform: "uppercase", letterSpacing: 1, marginBottom: 2 }}>
        Fill (confidence)
      </div>
      {row("#22c55e", t("legend.highConfidence"))}
      {row("#eab308", t("legend.mediumConfidence"))}
      {row("#94a3b8", t("legend.lowConfidence"))}
      <div style={{ color: "#aaa", fontSize: 11, textTransform: "uppercase", letterSpacing: 1, marginTop: 6, marginBottom: 2 }}>
        Ring (alert level)
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, lineHeight: 1.6 }}>
        <span style={{ width: 10, height: 10, borderRadius: "50%", border: "2px solid #dc2626", background: "transparent" }} />
        {t("legend.criticalAlert")}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, lineHeight: 1.6 }}>
        <span style={{ width: 10, height: 10, borderRadius: "50%", border: "2px solid #f97316", background: "transparent" }} />
        {t("legend.highAlert")}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, lineHeight: 1.6 }}>
        <span style={{ width: 10, height: 10, borderRadius: "50%", border: "2px solid #555", background: "transparent" }} />
        {t("legend.mediumAlert")}
      </div>
    </div>
  );
}
