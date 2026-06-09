"use client";
import { useEffect, useState } from "react";
import { api, Hotspot, HotspotSummary } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { parseCitations } from "@/lib/citations";
import TrustTierEditor from "@/components/TrustTierEditor";

export default function HotspotDetail({ hotspot, onClose }: { hotspot: Hotspot; onClose: () => void }) {
  const { token } = useAuth();
  const [summary, setSummary] = useState<HotspotSummary | null>(null);
  useEffect(() => {
    api.summary(hotspot.hotspot_id, token).then(setSummary).catch(() => setSummary(null));
  }, [hotspot.hotspot_id, token]);

  return (
    <aside style={{ position: "absolute", top: 12, right: 12, width: 340, background: "#111", color: "#eee", padding: 16, borderRadius: 8 }}>
      <button onClick={onClose} style={{ float: "right" }}>×</button>
      <h3>Hotspot #{hotspot.hotspot_id}</h3>
      <dl>
        <dt>Confidence (source reliability)</dt>
        <dd><b>conf_score: {hotspot.conf_score.toFixed(1)}</b></dd>
        <dt>Convergence (cross-domain co-occurrence)</dt>
        <dd><b>convergence_score: {hotspot.convergence_score.toFixed(1)}</b> — {hotspot.alert_level}</dd>
      </dl>
      <h4>AI Intelligence Brief</h4>
      {summary ? (
        <>
          {summary.conflict_detected && <p style={{ color: "#f87171" }}>Conflict detected across sources.</p>}
          {summary.summary ? (
            <p>
              {parseCitations(summary.summary).map((part, i) =>
                part.type === "cite" ? (
                  <sup key={i} style={{ color: "#60a5fa", cursor: "pointer", fontWeight: 600 }} title={`Source [${part.n}]`}>
                    [{part.n}]
                  </sup>
                ) : (
                  <span key={i}>{part.text}</span>
                )
              )}
            </p>
          ) : (
            <p>No SITREP generated (below LLM threshold).</p>
          )}
        </>
      ) : <p>Loading…</p>}
      <TrustTierEditor />
    </aside>
  );
}
