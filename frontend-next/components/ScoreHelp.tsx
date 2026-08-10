"use client";
import { useState } from "react";
import type { MessageKey } from "@/lib/i18n-core";
import { useT } from "@/lib/i18n";
import { COLOR, FONT, RADIUS, SPACE } from "@/lib/theme";

export default function ScoreHelp({ titleKey, bodyKeys }: { titleKey: MessageKey; bodyKeys: MessageKey[] }) {
  const { t } = useT();
  const [open, setOpen] = useState(false);

  return (
    <span style={{ position: "relative", display: "inline-flex", marginLeft: SPACE.xs }}>
      <button
        aria-label={`${t(titleKey)} — ${t("help.more")}`}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        style={{
          width: 16, height: 16, borderRadius: "50%", border: "none",
          background: COLOR.surfaceRaised, color: COLOR.textMuted,
          cursor: "help", fontSize: 11, fontWeight: 700, lineHeight: 1, padding: 0,
        }}
      >
        ?
      </button>
      {open && (
        <span
          role="tooltip"
          tabIndex={-1}
          onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); }}
          style={{
            position: "absolute", top: "calc(100% + 6px)", left: 0, zIndex: 30,
            background: COLOR.surface, border: `1px solid ${COLOR.border}`,
            borderRadius: RADIUS.md, padding: SPACE.sm, width: 260,
            color: COLOR.textMuted, fontSize: FONT.sm, lineHeight: 1.5,
            display: "flex", flexDirection: "column", gap: SPACE.xs,
            boxShadow: "0 4px 16px rgba(0,0,0,0.5)", fontWeight: 400,
          }}
        >
          {bodyKeys.map((k) => <span key={k}>{t(k)}</span>)}
        </span>
      )}
    </span>
  );
}
