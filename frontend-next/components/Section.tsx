"use client";
import { useState, type ReactNode } from "react";
import { COLOR, FONT, SPACE } from "@/lib/theme";

export default function Section({
  title, children, defaultOpen = true, count,
}: {
  title: string;
  children: ReactNode;
  defaultOpen?: boolean;
  count?: number;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section style={{ borderTop: `1px solid ${COLOR.border}`, marginTop: SPACE.lg }}>
      <h4 style={{ margin: 0 }}>
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
          style={{
            display: "flex", alignItems: "center", gap: SPACE.sm,
            width: "100%", padding: `${SPACE.md}px 0`,
            background: "none", border: "none", cursor: "pointer",
            color: COLOR.text, font: "inherit", fontSize: FONT.md,
            fontWeight: 600, textAlign: "left",
          }}
        >
          <span aria-hidden="true" style={{ color: COLOR.textDim, fontSize: FONT.xs }}>
            {open ? "▼" : "▶"}
          </span>
          {title}
          {count != null && " "}
          {count != null && (
            <span style={{ color: COLOR.textMuted, fontWeight: 400 }}>({count})</span>
          )}
        </button>
      </h4>
      {open && <div style={{ paddingBottom: SPACE.lg }}>{children}</div>}
    </section>
  );
}
