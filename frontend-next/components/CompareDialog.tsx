"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent } from "react";
import type { Claim, Hotspot, HotspotEvent, WindowReport } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { MessageKey } from "@/lib/i18n-core";
import { buildComparison, deltaTone, type Direction } from "@/lib/compare";
import { downloadText, toCsv, toJson, toMarkdown, type ExportPayload } from "@/lib/export";
import { TIME_WINDOW_HOURS, TIME_WINDOW_LABEL, type TimeWindow } from "@/lib/filters";
import { confTrusted, windowMetrics, type Window } from "@/lib/window-metrics";
import { consistencyTrusted, windowConsistency } from "@/lib/window-consistency";
import { COLOR, FONT, RADIUS, SPACE } from "@/lib/theme";

const GLYPH: Record<Direction, string> = { up: "↑", down: "↓", flat: "·", none: "—" };

export default function CompareDialog({ hotspot, events, claims, onClose }: {
  hotspot: Hotspot; events: HotspotEvent[]; claims: Claim[] | null; onClose: () => void;
}) {
  const { t } = useT();
  const { token } = useAuth();
  // The dialog only ever opens on a click, so this never runs during SSR; the
  // guard keeps a future server render from touching document. Portal to body
  // so the print stylesheet's `body > *:not(.print-root)` can isolate it.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  // now is pinned at open so the two windows do not shift under the analyst
  const [now] = useState(() => Date.now());
  const [duration, setDuration] = useState<TimeWindow>("24h");
  const [report, setReport] = useState<WindowReport | null>(null);
  const [reportError, setReportError] = useState(false);
  const [generating, setGenerating] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const durationRef = useRef(duration);
  useEffect(() => { durationRef.current = duration; }, [duration]);
  // A report (narrative + citations) describes one specific window; switching
  // the duration must not export the old narrative under the new headers.
  useEffect(() => {
    setReport(null);
    setReportError(false);
    setGenerating(false);
  }, [duration]);
  // A modal that opens on a click must take focus so Escape and Tab land on it,
  // and return it where it was when it closes.
  useEffect(() => {
    if (!mounted) return;
    const previous = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    return () => previous?.focus?.();
  }, [mounted]);

  const durMs = TIME_WINDOW_HOURS[duration] * 3600_000;
  const windows = useMemo(() => {
    const endB = now;
    const startB = now - durMs;
    const startA = startB - durMs;
    return {
      windowA: { from: new Date(startA).toISOString(), to: new Date(startB).toISOString() } as Window,
      windowB: { from: new Date(startB).toISOString(), to: new Date(endB).toISOString() } as Window,
    };
  }, [now, durMs]);

  const { rows } = useMemo(() => {
    const a = windowMetrics(events, windows.windowA);
    const b = windowMetrics(events, windows.windowB);
    const consistencyA = windowConsistency(claims ?? [], events, windows.windowA);
    const consistencyB = windowConsistency(claims ?? [], events, windows.windowB);
    const confOk = confTrusted(events, hotspot);
    const consOk = consistencyTrusted(claims ?? [], events, hotspot);
    const rows = buildComparison({
      a, b, consistencyA, consistencyB, confTrusted: confOk, consistencyTrusted: consOk,
    });
    return { rows };
  }, [events, claims, hotspot, windows.windowA, windows.windowB]);

  const generate = () => {
    if (generating) return;
    const requested = durationRef.current;
    setGenerating(true);
    setReportError(false);
    api.report(hotspot.hotspot_id, windows.windowB.from, windows.windowB.to, token)
      .then((r) => {
        // A response for a window the analyst has already switched away from
        // must not re-populate the panel.
        if (durationRef.current === requested) setReport(r);
        setGenerating(false);
      })
      .catch(() => { setReportError(true); setGenerating(false); });
  };

  const base = `${hotspot.name ?? hotspot.hotspot_id}-compare`;
  const payload: ExportPayload = {
    hotspot: hotspot.name ?? `Hotspot #${hotspot.hotspot_id}`,
    windowA: windows.windowA,
    windowB: windows.windowB,
    rows,
    citations: report?.citations ?? [],
  };

  const fmt = (v: number | null): string => v == null ? "—" : v.toFixed(1);
  const signed = (v: number | null): string => v == null ? "—" : (v > 0 ? "+" : "") + v.toFixed(1);
  const glyphColor = (d: Direction, key: string): string => {
    const tone = deltaTone(key, d);
    if (tone === "good") return COLOR.ok;
    if (tone === "bad") return COLOR.danger;
    return d === "none" ? COLOR.textDim : COLOR.textMuted;
  };

  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") { onClose(); return; }
    if (e.key !== "Tab") return;
    const focusables = panelRef.current?.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    if (!focusables || focusables.length === 0) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };

  if (!mounted) return null;
  return createPortal(
    <div className="print-root"
         style={{ position: "fixed", inset: 0, zIndex: 50, display: "flex",
                  alignItems: "center", justifyContent: "center", background: "rgba(0,0,0,0.6)", padding: SPACE.xl }}>
      <div role="dialog" aria-modal="true" aria-label={t("compare.title")}
           className="compare-panel" tabIndex={-1} ref={panelRef} onKeyDown={onKeyDown}
           style={{ background: COLOR.surface, color: COLOR.text, border: `1px solid ${COLOR.border}`,
                    borderRadius: RADIUS.lg, padding: SPACE.xl, width: 640, maxWidth: "100%",
                    maxHeight: "90vh", overflowY: "auto", boxShadow: "0 8px 32px rgba(0,0,0,0.6)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: SPACE.md }}>
          <h3 style={{ margin: 0 }}>{t("compare.title")}</h3>
          <button className="print-hide" onClick={onClose} aria-label={t("compare.close")}
                  style={{ background: COLOR.surfaceRaised, color: COLOR.text, border: `1px solid ${COLOR.border}`,
                           borderRadius: RADIUS.md, cursor: "pointer", width: 28, height: 28 }}>&times;</button>
        </div>

        <div style={{ display: "flex", gap: SPACE.lg, marginBottom: SPACE.lg, fontSize: FONT.md }}>
          <label style={{ display: "flex", alignItems: "center", gap: SPACE.sm }}>
            {t("filter.timeWindow")}
            <select value={duration} onChange={(e) => setDuration(e.target.value as TimeWindow)}
                    style={{ background: COLOR.surfaceRaised, color: COLOR.text, border: `1px solid ${COLOR.border}`,
                             borderRadius: RADIUS.sm, padding: "2px 6px" }}>
              {(Object.keys(TIME_WINDOW_HOURS) as TimeWindow[]).map((k) => (
                <option key={k} value={k}>{t(TIME_WINDOW_LABEL[k] as MessageKey)}</option>
              ))}
            </select>
          </label>
          <span style={{ color: COLOR.textMuted }}>
            <b>{t("compare.windowA")}</b> {new Date(windows.windowA.from).toLocaleString()} — {new Date(windows.windowA.to).toLocaleString()}
          </span>
          <span style={{ color: COLOR.textMuted }}>
            <b>{t("compare.windowB")}</b> {new Date(windows.windowB.from).toLocaleString()} — {new Date(windows.windowB.to).toLocaleString()}
          </span>
        </div>

        <p style={{ fontSize: FONT.sm, color: COLOR.textMuted, margin: `0 0 ${SPACE.md}px` }}>
          {t("compare.recomputed")}
        </p>

        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: FONT.md }}>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} style={{ borderBottom: `1px solid ${COLOR.border}` }}>
                <td style={{ padding: `${SPACE.sm}px 0` }}>
                  {t(r.labelKey as MessageKey)}
                  {!r.trusted && (
                    <span style={{ display: "block", color: COLOR.textDim, fontSize: FONT.xs }}>
                      {t("compare.untrusted")}
                    </span>
                  )}
                </td>
                <td style={{ padding: `${SPACE.sm}px 0`, textAlign: "right" }}>{fmt(r.a)}</td>
                <td style={{ padding: `${SPACE.sm}px 0`, textAlign: "center", width: 28, color: glyphColor(r.direction, r.key) }}>
                  {GLYPH[r.direction]}
                </td>
                <td style={{ padding: `${SPACE.sm}px 0`, textAlign: "right" }}>{fmt(r.b)}</td>
                <td style={{ padding: `${SPACE.sm}px 0`, textAlign: "right", color: glyphColor(r.direction, r.key) }}>
                  {signed(r.delta)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.some((r) => r.key === "consistency") && (
          <p style={{ fontSize: FONT.sm, color: COLOR.textDim, margin: `${SPACE.sm}px 0 0` }}>
            {t("compare.retrospective")}
          </p>
        )}

        {report && (
          <section style={{ marginTop: SPACE.lg }}>
            <h4 style={{ margin: `0 0 ${SPACE.xs}px` }}>{t("compare.narrative")}</h4>
            <p style={{ fontSize: FONT.md, margin: 0 }}>{report.narrative}</p>
          </section>
        )}
        {generating && <p style={{ fontSize: FONT.sm, color: COLOR.textMuted }}>{t("compare.generating")}</p>}
        {reportError && <p style={{ fontSize: FONT.sm, color: COLOR.danger }}>{t("compare.reportUnavailable")}</p>}

        <div className="print-hide" style={{ display: "flex", gap: SPACE.md, flexWrap: "wrap", marginTop: SPACE.lg }}>
          <button onClick={generate} style={buttonStyle} disabled={generating}>{t("compare.generate")}</button>
          <button onClick={() => downloadText(`${base}.csv`, "text/csv", toCsv(rows))} style={buttonStyle}>{t("compare.exportCsv")}</button>
          <button onClick={() => downloadText(`${base}.json`, "application/json", toJson(payload))} style={buttonStyle}>{t("compare.exportJson")}</button>
          <button onClick={() => downloadText(`${base}.md`, "text/markdown", toMarkdown(payload, report?.narrative ?? null))} style={buttonStyle}>{t("compare.exportMd")}</button>
          <button onClick={() => window.print()} style={buttonStyle}>{t("compare.print")}</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

const buttonStyle: CSSProperties = {
  background: COLOR.surfaceRaised, color: COLOR.text, padding: `${SPACE.sm}px ${SPACE.md}px`,
  borderRadius: RADIUS.md, border: `1px solid ${COLOR.border}`, cursor: "pointer", fontSize: FONT.md,
};
