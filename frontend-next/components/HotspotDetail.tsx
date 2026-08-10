"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, Claim, ClaimEvidence, Hotspot, HotspotClaims, HotspotEvent, HotspotSummary } from "@/lib/api";
import { orderClaims, splitEvidence, statusColor, statusLabelKey } from "@/lib/claims";
import type { MessageKey } from "@/lib/i18n-core";
import { useAuth } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { parseCitations } from "@/lib/citations";
import { sitrepState } from "@/lib/sitrep";
import { buildSubtitle } from "@/lib/subtitle";
import { formatIntensity, formatTone, maxFatalities, meanTone } from "@/lib/severity";
import { bucketByDay } from "@/lib/sparkline";
import TrustTierEditor from "@/components/TrustTierEditor";
import CompareDialog from "@/components/CompareDialog";
import Sparkline from "@/components/Sparkline";
import Section from "@/components/Section";
import StackedBar from "@/components/StackedBar";
import MixBars from "@/components/MixBars";
import ScoreHelp from "@/components/ScoreHelp";
import { confBreakdown, consistencyMix, convergenceBreakdown, sourceMix } from "@/lib/score-breakdown";
import { COLOR, FONT, RADIUS, SPACE, buttonStyle, chipStyle } from "@/lib/theme";

export default function HotspotDetail({ hotspot, onClose }: { hotspot: Hotspot; onClose: () => void }) {
  const { token } = useAuth();
  const { t } = useT();
  const [summary, setSummary] = useState<HotspotSummary | null>(null);
  const [events, setEvents] = useState<HotspotEvent[]>([]);
  const [claims, setClaims] = useState<HotspotClaims | null>(null);
  const [flash, setFlash] = useState<number | null>(null);
  // Sources must stay reachable by citation jumps: a collapsed Section unmounts
  // its <ol>, so jumpTo forces it open before scrolling (FR-16).
  const [sourcesOpen, setSourcesOpen] = useState(true);
  const listRef = useRef<HTMLOListElement>(null);
  const [summaryError, setSummaryError] = useState(false);
  const [eventsError, setEventsError] = useState(false);
  const [comparing, setComparing] = useState(false);
  // one generation ref per resource — a shared counter would let the last
  // synchronous fetcher (claims) invalidate the two that started earlier
  const summaryGen = useRef(0);
  const eventsGen = useRef(0);
  const claimsGen = useRef(0);

  // guard every set* with a generation check so a stale in-flight response
  // (older retry, or a previous hotspot) can never populate this panel
  const fetchSummary = useCallback(() => {
    const gen = ++summaryGen.current;
    api.summary(hotspot.hotspot_id, token)
      .then((s) => { if (summaryGen.current === gen) setSummary(s); })
      .catch(() => { if (summaryGen.current === gen) setSummaryError(true); });
  }, [hotspot.hotspot_id, token]);

  const fetchEvents = useCallback(() => {
    const gen = ++eventsGen.current;
    api.hotspotEvents(hotspot.hotspot_id, token)
      .then((e) => { if (eventsGen.current === gen) setEvents(e); })
      .catch(() => { if (eventsGen.current === gen) setEventsError(true); });
  }, [hotspot.hotspot_id, token]);

  const fetchClaims = useCallback(() => {
    const gen = ++claimsGen.current;
    api.hotspotClaims(hotspot.hotspot_id, token)
      .then((c) => { if (claimsGen.current === gen) setClaims(c); })
      .catch(() => { if (claimsGen.current === gen) setClaims(null); });
  }, [hotspot.hotspot_id, token]);

  useEffect(() => { fetchSummary(); fetchEvents(); fetchClaims(); }, [fetchSummary, fetchEvents, fetchClaims]);

  const retrySummary = () => { setSummaryError(false); fetchSummary(); };
  const retryEvents = () => { setEventsError(false); fetchEvents(); };

  const retryButtonStyle = { background: COLOR.surfaceRaised, color: COLOR.text, padding: "2px 10px", borderRadius: 4, border: "none", cursor: "pointer", fontSize: 12, marginLeft: 8 };

  const jumpTo = (n: number) => {
    setSourcesOpen(true);
    const row = listRef.current?.querySelector<HTMLElement>(`[data-cite="${n}"]`);
    row?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    setFlash(n);
    setTimeout(() => setFlash(null), 1200);
  };

  const cited = events.filter((e) => e.citation_index !== null);
  // provenance badges only earn their row-height when the hotspot actually
  // mixes systems/types — a single-GDELT hotspot shows them identically on
  // every row, so they are inert chrome there
  const distinctSystems = new Set(events.map((e) => e.source_system)).size > 1;
  const distinctTypes = new Set(events.map((e) => e.event_type_label)).size > 1;
  // The per-source badges are terse ("sắc thái -6.1"); the legend explains only
  // the metrics this hotspot actually renders, so a single-type hotspot with no
  // tone does not carry a legend for bars it never draws.
  const hasTone = events.some((e) => e.avg_tone != null);
  const hasIntensity = events.some((e) => e.goldstein_scale != null);
  const hasFatalities = events.some((e) => (e.fatalities ?? 0) > 0);
  const hasReports = events.some((e) => (e.duplicate_count ?? 1) > 1);
  const hasArticles = events.some((e) => (e.num_sources ?? 1) > 1);
  const hasTrust = events.some((e) => e.trust_tier != null);
  const sourceLegend = [
    hasTone && { key: "tone", text: t("sources.legend.tone") },
    hasIntensity && { key: "intensity", text: t("sources.legend.intensity") },
    hasTrust && { key: "trustTier", text: t("sources.legend.trustTier") },
    hasReports && { key: "reports", text: t("sources.legend.reports") },
    hasArticles && { key: "articles", text: t("sources.legend.articles") },
    hasFatalities && { key: "fatalities", text: t("sources.legend.fatalities") },
  ].filter(Boolean) as { key: string; text: string }[];

  return (
    <aside style={{ width: 340, flexShrink: 0, height: "100%", overflowY: "auto", background: COLOR.surface, color: COLOR.text, padding: 16, boxSizing: "border-box" }}>
      <button onClick={onClose} style={{ float: "right" }}>&times;</button>
      <h3 style={{ marginBottom: 2 }}>{hotspot.name ?? `Hotspot #${hotspot.hotspot_id}`}</h3>
      <p style={{ marginTop: 0, fontSize: 12, color: COLOR.textMuted }}>{buildSubtitle(events, t)}</p>
      {(() => {
        const fat = maxFatalities(events);
        const tone = meanTone(events);
        if (fat == null && tone == null && hotspot.start_window == null) return null;
        const sameDay = hotspot.start_window && hotspot.end_window &&
          new Date(hotspot.start_window).toDateString() === new Date(hotspot.end_window).toDateString();
        return (
          <p style={{ marginTop: 0, marginBottom: 8, fontSize: 11, color: COLOR.textMuted }}>
            {fat != null && <span style={{ color: "#fca5a5" }}>{fat} {t("detail.maxFatalities")}</span>}
            {fat != null && tone != null && " · "}
            {tone != null && <span>{t("detail.tone")} {tone.toFixed(1)}</span>}
            {hotspot.start_window && (
              <>
                <br />
                {t("detail.activeSince")} {new Date(hotspot.start_window).toLocaleDateString()}
                {hotspot.end_window && !sameDay && <> · {t("detail.lastSeen")} {new Date(hotspot.end_window).toLocaleDateString()}</>}
              </>
            )}
          </p>
        );
      })()}
      <Section title={t("detail.section.scores")}>
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: SPACE.sm }}>
          <button onClick={() => setComparing(true)} style={{ ...buttonStyle, fontSize: FONT.sm }}>
            {t("compare.open")}
          </button>
        </div>
        {comparing && (
          <CompareDialog
            hotspot={hotspot}
            events={events}
            claims={claims?.claims ?? null}
            onClose={() => setComparing(false)}
          />
        )}
        <dl style={{ margin: 0 }}>
        <dt style={{ fontSize: FONT.sm, color: COLOR.textMuted }}>
          {t("detail.confidence")}
          <ScoreHelp titleKey="help.confidence.title" bodyKeys={["help.confidence.what", "help.confidence.read", "help.confidence.trap"]} />
        </dt>
        <dd style={{ margin: 0, marginBottom: SPACE.lg }}>
          <b>{hotspot.conf_score.toFixed(1)}</b>
          {(() => {
            const b = confBreakdown(hotspot);
            if (b.mode === "unavailable") {
              return <p style={{ fontSize: FONT.sm, color: COLOR.textDim, margin: `${SPACE.xs}px 0 0` }}>
                {t("breakdown.unavailable")}
              </p>;
            }
            if (b.mode === "raw") {
              return <p style={{ fontSize: FONT.sm, color: COLOR.textMuted, margin: `${SPACE.xs}px 0 0` }}>
                {t("breakdown.rawInputs")}<br />
                {t("breakdown.sourceDensity")} {b.sourceDensity.toFixed(2)} ·{" "}
                {t("breakdown.diversity")} {b.diversity.toFixed(2)}
              </p>;
            }
            return (
              <div style={{ marginTop: SPACE.sm }}>
                <StackedBar
                  label={t("detail.confidence")}
                  segments={[
                    { label: t("breakdown.sourceDensity"), value: b.density, color: COLOR.accent },
                    { label: t("breakdown.diversity"), value: b.diversity, color: COLOR.accentAlt },
                  ]}
                />
              </div>
            );
          })()}
        </dd>
        <dt style={{ fontSize: FONT.sm, color: COLOR.textMuted }}>
          {t("detail.convergence")}
          <ScoreHelp titleKey="help.convergence.title" bodyKeys={["help.convergence.what", "help.convergence.read", "help.convergence.trap"]} />
        </dt>
        <dd style={{ margin: 0 }}>
          <b>{hotspot.convergence_score == null ? "—" : hotspot.convergence_score.toFixed(1)}</b>
          {hotspot.convergence_score != null && <> — {hotspot.alert_level}</>}
          {(() => {
            const b = convergenceBreakdown(hotspot);
            if (b.mode === "unavailable") {
              // NULL convergence_score = never went through grid-cell
              // convergence, not a genuine zero — the honest answer is
              // "not scored", not a hollow bar.
              return <p style={{ fontSize: FONT.sm, color: COLOR.textDim, margin: `${SPACE.xs}px 0 0` }}>
                {t("breakdown.unavailable")}
              </p>;
            }
            if (b.mode === "raw") {
              // The convergence formula is hardcoded (types*25 + min(25,
              // events*2)), unlike conf_score's env-overridable weights, so a
              // reconstruction miss can only mean inconsistent inputs. The
              // caveat is the whole story — bare inputs under the printed
              // score would read as an explanation.
              return <p style={{ fontSize: FONT.sm, color: COLOR.textMuted, margin: `${SPACE.xs}px 0 0` }}>
                {t("breakdown.rawConvergence")}
              </p>;
            }
            return (
              <div style={{ marginTop: SPACE.sm }}>
                <StackedBar
                  label={t("detail.convergence")}
                  clampNote={t("breakdown.clamped")}
                  segments={[
                    { label: t("breakdown.typeScore"), value: b.typeScore, color: COLOR.accent },
                    { label: t("breakdown.countBoost"), value: b.countBoost, color: COLOR.accentAlt },
                  ]}
                />
                <p style={{ fontSize: FONT.sm, color: COLOR.textDim, margin: `${SPACE.xs}px 0 0` }}>
                  {t("breakdown.typesEvents")
                    .replace("{types}", String(b.types))
                    .replace("{events}", String(b.events))}
                  {b.clamped && ` · ${t("breakdown.clamped")}`}
                </p>
              </div>
            );
          })()}
        </dd>
        </dl>
      </Section>
      <Section title={t("detail.section.brief")}>
        {summary ? (
          <>
            {summary.conflict_detected && <p style={{ color: COLOR.danger }}>{t("detail.conflictDetected")}</p>}
            {summary.summary ? (
              <p>
                {parseCitations(summary.summary).map((part, i) =>
                  part.type === "cite" ? (
                    <sup key={i} role="button" onClick={() => jumpTo(part.n)}
                         style={{ color: COLOR.accent, cursor: "pointer", fontWeight: 600 }}>
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
        ) : summaryError ? (
          <p>{t("detail.error")} <button onClick={retrySummary} style={retryButtonStyle}>{t("detail.retry")}</button></p>
        ) : (
          <p>{t("detail.loading")}</p>
        )}
      </Section>
      {(hotspot.consistency_score != null || (claims?.claims.length ?? 0) > 0) && (
        <Section title={t("detail.section.evidence")} count={claims?.claims.length}>
          {hotspot.consistency_score != null && (
            <p style={{ fontSize: 13 }}>
              <b>{t("detail.consistencyScore")}<ScoreHelp titleKey="help.consistency.title" bodyKeys={["help.consistency.what", "help.consistency.read", "help.consistency.trap"]} />: {hotspot.consistency_score.toFixed(1)}</b>
              {claims?.insufficient_sources && (
                <span style={{ color: COLOR.textMuted }}> — {t("detail.insufficientSources")}</span>
              )}
            </p>
          )}
          {(() => {
            const mix = consistencyMix(claims?.claims ?? []);
            if (mix.length === 0) return null;
            return (
              <div style={{ marginBottom: SPACE.md }}>
                <StackedBar
                  label={t("detail.consistency")}
                  max={mix.reduce((a, m) => a + m.count, 0)}
                  segments={mix.map((m) => ({
                    label: t(`claims.${m.label}` as MessageKey),
                    value: m.count,
                    color: statusColor(m.label as Claim["status"]),
                  }))}
                />
              </div>
            );
          })()}
          <ul style={{ paddingLeft: 0, listStyle: "none", fontSize: 13 }}>
            {orderClaims(claims?.claims ?? []).map((c) => (
              <li key={c.claim_id} style={{ marginBottom: 6 }}>
                <span style={{ color: statusColor(c.status), fontWeight: 600 }}>
                  {t(statusLabelKey(c.status) as MessageKey)}
                </span>{" "}
                {c.claim_text}
                {(() => {
                  const { supporting, contradicting } = splitEvidence(c);
                  // inline probability is dispute-only: on supporting citations it is
                  // near-constant (p≈1.00) and reads as noise; the title tooltip stays
                  // on every citation so the number is still one hover away
                  const cite = (e: ClaimEvidence, color: string, showProb: boolean) => (
                    <sup key={e.event_id} role="button"
                         onClick={() => jumpTo(e.citation_index as number)}
                         title={e.probability != null
                           ? `${t("detail.probability")} ${e.probability.toFixed(2)}`
                           : undefined}
                         style={{ color, cursor: "pointer", fontWeight: 600 }}>
                      [{e.citation_index}]
                      {showProb && e.probability != null && (
                        <span style={{ fontWeight: 400, opacity: 0.75 }}>
                          {" "}p={e.probability.toFixed(2)}
                        </span>
                      )}
                    </sup>
                  );
                  return (
                    <div style={{ fontSize: 11, color: COLOR.textMuted, marginTop: 2 }}>
                      {supporting.length > 0 && (
                        <span>
                          {t("claims.supportedBy")}{" "}
                          {supporting.map((e) => cite(e, COLOR.accent, false))}
                        </span>
                      )}
                      {supporting.length > 0 && contradicting.length > 0 && " · "}
                      {contradicting.length > 0 && (
                        <span>
                          {t("claims.contradictedBy")}{" "}
                          {contradicting.map((e) => cite(e, COLOR.danger, true))}
                        </span>
                      )}
                    </div>
                  );
                })()}
              </li>
            ))}
          </ul>
        </Section>
      )}
      {events.length > 0 && (() => {
        const buckets = bucketByDay(events, 14);
        // per-tick clustering lands all events on one day, so a 14-day window is
        // a single spike — hide the sparkline rather than draw inert chrome
        if (buckets.filter((b) => b.count > 0).length <= 1) return null;
        return (
          <Section title={t("detail.section.activity")}>
            <Sparkline counts={buckets.map((b) => b.count)} label={t("detail.activity")} />
          </Section>
        );
      })()}
      {events.length > 0 && (() => {
        const mix = sourceMix(events);
        return (
          <Section title={t("detail.section.sourceMix")} defaultOpen={false}>
            <p style={{ fontSize: FONT.sm, color: COLOR.textMuted, marginTop: 0 }}>
              {t("breakdown.uniqueDomains").replace("{n}", String(mix.uniqueDomains))}
            </p>
            <MixBars
              title={t("breakdown.trustTiers")}
              entries={mix.tiers.map((e) => ({ ...e, label: t("breakdown.tier").replace("{n}", e.label) }))}
            />
            <MixBars
              title={t("breakdown.countries")}
              entries={mix.countries.map((e) => ({
                ...e,
                label: e.label === "??" ? t("breakdown.unknownCountry") : e.label,
              }))}
            />
          </Section>
        );
      })()}
      <Section title={t("detail.section.sources")} count={eventsError ? undefined : cited.length}
               open={sourcesOpen} onOpenChange={setSourcesOpen}>
        {eventsError ? (
          <p>{t("detail.error")} <button onClick={retryEvents} style={retryButtonStyle}>{t("detail.retry")}</button></p>
        ) : (
        <>
        {sourceLegend.length > 0 && (
          <div style={{ fontSize: 11, color: COLOR.textDim, background: COLOR.surfaceRaised,
                        borderRadius: RADIUS.sm, padding: `${SPACE.xs}px ${SPACE.sm}px`,
                        marginBottom: SPACE.sm, lineHeight: 1.6 }}>
            {sourceLegend.map((item) => <div key={item.key}>{item.text}</div>)}
          </div>
        )}
        <ol ref={listRef} style={{ paddingLeft: 20, fontSize: FONT.md }}>
          {cited.map((e) => (
            <li key={e.event_id} data-cite={e.citation_index}
                style={{ marginBottom: 6, transition: "background 0.3s",
                         background: flash === e.citation_index ? "#1d4ed8" : "transparent" }}>
              <a href={e.url ?? "#"} target="_blank" rel="noopener noreferrer"
                 style={{ color: COLOR.link }}>
                {e.title || e.domain}
              </a>
              <div style={{ color: COLOR.textMuted, fontSize: 11 }}>
                {e.domain}
                {e.trust_tier !== null && <> &middot; {t("detail.trustTier")} {e.trust_tier}</>}
                {" · "}{new Date(e.event_date).toLocaleDateString()}
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 3 }}>
                {e.duplicate_count > 1 && (
                  <span style={chipStyle}
                        title={t("detail.reportsTooltip").replace("{n}", String(e.duplicate_count))}>
                    {e.duplicate_count} {t("detail.reports")}
                  </span>
                )}
                {distinctSystems && (
                  <span style={chipStyle}>
                    {e.source_system}
                  </span>
                )}
                {distinctTypes && (
                  <span style={chipStyle}>
                    {e.event_type_label}
                  </span>
                )}
                {e.fatalities != null && e.fatalities > 0 && (
                  <span style={{ ...chipStyle, background: COLOR.dangerSurface, color: COLOR.dangerText }}>
                    {e.fatalities} {t("detail.fatalities")}
                  </span>
                )}
                {e.num_sources != null && e.num_sources > 1 && (
                  <span style={chipStyle}>
                    {e.num_sources} {t("detail.numSources")}
                  </span>
                )}
                {formatIntensity(e.goldstein_scale) && (
                  <span style={chipStyle}>
                    {t("detail.intensity")} {formatIntensity(e.goldstein_scale)}
                  </span>
                )}
                {formatTone(e.avg_tone) && (
                  <span style={chipStyle}>
                    {t("detail.tone")} {formatTone(e.avg_tone)}
                  </span>
                )}
              </div>
            </li>
          ))}
        </ol>
        </>
        )}
      </Section>
      <TrustTierEditor />
    </aside>
  );
}
