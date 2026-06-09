"use client";
import { useEffect, useState } from "react";
import { api, Source } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function TrustTierEditor() {
  const { token, isAdmin } = useAuth();
  const [sources, setSources] = useState<Source[]>([]);
  const [saving, setSaving] = useState<number | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token || !isAdmin) return;
    api.sources(token).then(setSources).catch(() => setError("Failed to load sources"));
  }, [token, isAdmin]);

  const update = async (sourceId: number, trustTier: number) => {
    if (!token) return;
    setSaving(sourceId);
    setError("");
    try {
      await api.updateTrustTier(sourceId, trustTier, token);
      setSources((prev) => prev.map((s) => (s.source_id === sourceId ? { ...s, trust_tier: trustTier } : s)));
    } catch {
      setError("Failed to update trust tier");
    } finally {
      setSaving(null);
    }
  };

  if (!isAdmin) return null;

  return (
    <div style={{ padding: 12, background: "#111", color: "#eee", borderRadius: 8, marginTop: 8 }}>
      <h4 style={{ margin: "0 0 8px" }}>Source Trust Tiers (Admin)</h4>
      {error && <p style={{ color: "#f87171", margin: 0 }}>{error}</p>}
      {sources.length === 0 && <p style={{ margin: 0, color: "#999" }}>No sources loaded.</p>}
      <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 300, overflowY: "auto" }}>
        {sources.map((s) => (
          <div key={s.source_id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>{s.domain}</span>
            <select
              value={s.trust_tier ?? 1}
              disabled={saving === s.source_id}
              onChange={(e) => update(s.source_id, Number(e.target.value))}
              style={{ padding: "4px 8px", borderRadius: 4, border: "1px solid #333", background: "#0f3460", color: "#eee", fontSize: 12 }}
            >
              <option value={1}>Tier 1 (wire/gov — highest trust)</option>
              <option value={2}>Tier 2 (major outlets)</option>
              <option value={3}>Tier 3 (specialist/regional)</option>
              <option value={4}>Tier 4 (aggregators/unknown — lowest)</option>
            </select>
          </div>
        ))}
      </div>
    </div>
  );
}
