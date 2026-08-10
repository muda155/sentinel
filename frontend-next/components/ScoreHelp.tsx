"use client";
import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { MessageKey } from "@/lib/i18n-core";
import { useT } from "@/lib/i18n";
import { COLOR, FONT, RADIUS, SPACE } from "@/lib/theme";

const WIDTH = 260;
const GUTTER = 8;

export default function ScoreHelp({ titleKey, bodyKeys }: { titleKey: MessageKey; bodyKeys: MessageKey[] }) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  // The detail panel scrolls (overflow-y: auto), which forces horizontal
  // clipping, so an inline tooltip anchored to the button gets cut at the panel
  // edge — which for this right-side panel is the screen edge. Portaling to
  // body with a clamped fixed position keeps the whole tip on screen.
  useLayoutEffect(() => {
    if (!open) return;
    const btn = btnRef.current?.getBoundingClientRect();
    const tip = tipRef.current?.getBoundingClientRect();
    if (!btn || !tip) return;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let left = Math.max(GUTTER, btn.right - WIDTH);
    let top = btn.bottom + 6;
    if (top + tip.height > vh - GUTTER) top = Math.max(GUTTER, btn.top - 6 - tip.height);
    setPos({ left, top });
  }, [open]);

  // Escape must close regardless of where focus is — the tip is portaled, so a
  // handler on it would only fire while the (unfocused) tip has keyboard focus.
  useLayoutEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <span style={{ display: "inline-flex", marginLeft: SPACE.xs }}>
      <button
        ref={btnRef}
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
      {open && createPortal(
        <div
          ref={tipRef}
          role="tooltip"
          tabIndex={-1}
          style={{
            position: "fixed", top: pos.top, left: pos.left, width: WIDTH, zIndex: 50,
            background: COLOR.surface, border: `1px solid ${COLOR.border}`,
            borderRadius: RADIUS.md, padding: SPACE.sm,
            color: COLOR.textMuted, fontSize: FONT.sm, lineHeight: 1.5,
            display: "flex", flexDirection: "column", gap: SPACE.xs,
            boxShadow: "0 4px 16px rgba(0,0,0,0.5)", fontWeight: 400,
          }}
        >
          {bodyKeys.map((k) => <span key={k}>{t(k)}</span>)}
        </div>,
        document.body,
      )}
    </span>
  );
}
