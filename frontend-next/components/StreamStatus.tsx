"use client";
import { useEffect, useState } from "react";
import { useT } from "@/lib/i18n";
import type { MessageKey } from "@/lib/locales/en";
import { relativeAge, STATUS_COLOR, STATUS_LABEL, type StreamStatus } from "@/lib/stream-status";

export default function StreamStatusDot(
  { status, lastEventAt }: { status: StreamStatus; lastEventAt: number | null },
) {
  const { t } = useT();
  const [now, setNow] = useState<number>(() => Date.now());

  // The 1s ticker lives in this component on purpose. Hoisting it into
  // app/page.tsx would re-render MapView — and rebuild its deck.gl layers —
  // once per second for a label that only this element shows.
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const label = t(STATUS_LABEL[status] as MessageKey);
  const age = lastEventAt == null
    ? t("stream.noEvents")
    : t("stream.updated").replace("{t}", relativeAge(now - lastEventAt));

  return (
    <span
      title={`${label} · ${age}`}
      aria-label={`${label} · ${age}`}
      style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#9ca3af" }}
    >
      <span
        data-testid="stream-dot"
        style={{
          width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
          background: STATUS_COLOR[status],
        }}
      />
      <span style={{ whiteSpace: "nowrap" }}>{age}</span>
    </span>
  );
}
