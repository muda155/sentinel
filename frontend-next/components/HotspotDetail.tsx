"use client";
import { useEffect, useRef, useState } from "react";
import { api, Claim, ClaimEvidence, Hotspot, HotspotClaims, HotspotEvent, HotspotSummary } from "@/lib/api";
import { orderClaims, splitEvidence, statusColor, statusLabelKey } from "@/lib/claims";
import type { MessageKey } from "@/lib/i18n-core";
import { useAuth } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { parseCitations } from "@/lib/citations";
import { sitrepState } from "@/lib/sitrep";
import { buildSubtitle } from "@/lib/subtitle";
import TrustTierEditor from "@/components/TrustTierEditor";

export default function HotspotDetail({ hotspot, onClose }: { hotspot: Hotspot; onClose: () => void }) {
  const { token } = useAuth();
  const { t } = useT();
  const [summary, setSummary] = useState<HotspotSummary | null>(null);
  const [events, setEvents] = useState<HotspotEvent[]>([]);
  const [claims, setClaims] = useState<HotspotClaims | null>(null);
  const [flash, setFlash] = useState<number | null>(null);
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    api.summary(hotspot.hotspot_id, token).then(setSummary).catch(() => setSummary(null));
    api.hotspotEvents(hotspot.hotspot_id, token).then(setEvents).catch(() => setEvents([]));
    api.hotspotClaims(hotspot.hotspot_id, token).then(setClaims).catch(() => setClaims(null));
  }, [hotspot.hotspot_id, token]);

  const jumpTo = (n: number) => {
    const row = listRef.current?.querySelector<HTMLElement>(`[data-cite="${n}"]`);
    row?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    setFlash(n);
    setTimeout(() => setFlash(null), 1200);
  };

  const cited = events.filter((e) => e.citation_index !== null);

  return (
    <aside style={{ width: 340, flexShrink: 0, height: "100%", overflowY: "auto", background: "#111", color: "#eee", padding: 16, boxSizing: "border-box" }}>
      <button onClick={onClose} style={{ float: "right" }}>&times;</button>
      <h3 style={{ marginBottom: 2 }}>{hotspot.name ?? `Hotspot #${hotspot.hotspot_id}`}</h3>
      <p style={{ marginTop: 0, fontSize: 12, color: "#9ca3af" }}>{buildSubtitle(events, t)}</p>
      <dl>
        <dt>{t("detail.confidence")}</dt>
        <dd><b>conf_score: {hotspot.conf_score.toFixed(1)}</b></dd>
        <dt>{t("detail.convergence")}</dt>
        <dd><b>convergence_score: {hotspot.convergence_score.toFixed(1)}</b> — {hotspot.alert_level}</dd>
      </dl>
      <h4>{t("detail.aiBrief")}</h4>
      {summary ? (
        <>
          {summary.conflict_detected && <p style={{ color: "#f87171" }}>{t("detail.conflictDetected")}</p>}
          {summary.summary ? (
            <p>
              {parseCitations(summary.summary).map((part, i) =>
                part.type === "cite" ? (
                  <sup key={i} role="button" onClick={() => jumpTo(part.n)}
                       style={{ color: "#60a5fa", cursor: "pointer", fontWeight: 600 }}>
                    [{part.n}]
                  </sup>
                ) : (
                  <span key={i}>{part.text}</span>
                )
              )}
            </p>
          ) : (
            <p>
              {sitrepState(summary.summary, summary.conf_score) === "pending"
                ? t("detail.sitrepPending")
                : t("detail.noSitrepBelowThreshold")}
            </p>
          )}
        </>
      ) : <p>{t("detail.loading")}</p>}
      {(hotspot.consistency_score != null || (claims?.claims.length ?? 0) > 0) && (
        <>
          <h4>{t("detail.consistency")}</h4>
          {hotspot.consistency_score != null && (
            <p style={{ fontSize: 13 }}>
              <b>{t("detail.consistencyScore")}: {hotspot.consistency_score.toFixed(1)}</b>
              {claims?.insufficient_sources && (
                <span style={{ color: "#9ca3af" }}> — {t("detail.insufficientSources")}</span>
              )}
            </p>
          )}
          <ul style={{ paddingLeft: 0, listStyle: "none", fontSize: 13 }}>
            {orderClaims(claims?.claims ?? []).map((c) => (
              <li key={c.claim_id} style={{ marginBottom: 6 }}>
                <span style={{ color: statusColor(c.status), fontWeight: 600 }}>
                  {t(statusLabelKey(c.status) as MessageKey)}
                </span>{" "}
                {c.claim_text}
                {(() => {
                  const { supporting, contradicting } = splitEvidence(c);
                  const cite = (e: ClaimEvidence, color: string) => (
                    <sup key={e.event_id} role="button"
                         onClick={() => jumpTo(e.citation_index as number)}
                         style={{ color, cursor: "pointer", fontWeight: 600 }}>
                      [{e.citation_index}]
                    </sup>
                  );
                  return (
                    <div style={{ fontSize: 11, color: "#9ca3af", marginTop: 2 }}>
                      {supporting.length > 0 && (
                        <span>
                          {t("claims.supportedBy")}{" "}
                          {supporting.map((e) => cite(e, "#60a5fa"))}
                        </span>
                      )}
                      {supporting.length > 0 && contradicting.length > 0 && " · "}
                      {contradicting.length > 0 && (
                        <span>
                          {t("claims.contradictedBy")}{" "}
                          {contradicting.map((e) => cite(e, "#f87171"))}
                        </span>
                      )}
                    </div>
                  );
                })()}
              </li>
            ))}
          </ul>
        </>
      )}
      <h4>{t("detail.sources")} ({cited.length})</h4>
      <ol ref={listRef} style={{ paddingLeft: 20, fontSize: 13 }}>
        {cited.map((e) => (
          <li key={e.event_id} data-cite={e.citation_index}
              style={{ marginBottom: 6, transition: "background 0.3s",
                       background: flash === e.citation_index ? "#1d4ed8" : "transparent" }}>
            <a href={e.url ?? "#"} target="_blank" rel="noopener noreferrer"
               style={{ color: "#93c5fd" }}>
              {e.title || e.domain}
            </a>
            <div style={{ color: "#9ca3af", fontSize: 11 }}>
              {e.domain}
              {e.trust_tier !== null && <> &middot; {t("detail.trustTier")} {e.trust_tier}</>}
              {" · "}{new Date(e.event_date).toLocaleDateString()}
            </div>
          </li>
        ))}
      </ol>
      <TrustTierEditor />
    </aside>
  );
}
