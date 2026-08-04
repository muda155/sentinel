"use client";
import { useState, type ReactNode } from "react";
import { COLOR, FONT, SPACE } from "@/lib/theme";

export default function Section({
  title, children, defaultOpen = true, count, open: openProp, onOpenChange,
}: {
  title: string;
  children: ReactNode;
  defaultOpen?: boolean;
  count?: number;
  /** Controlled mode: caller owns the open state (e.g. HotspotDetail needs to
   *  force the Sources section open when a citation jump targets it). */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const [openState, setOpenState] = useState(defaultOpen);
  const open = openProp ?? openState;
  const toggle = () => {
    if (openProp === undefined) setOpenState((o) => !o);
    else onOpenChange?.(!openProp);
  };
  return (
    <section style={{ borderTop: `1px solid ${COLOR.border}`, marginTop: SPACE.lg }}>
      <h4 style={{ margin: 0 }}>
        <button
          type="button"
          aria-expanded={open}
          onClick={toggle}
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
