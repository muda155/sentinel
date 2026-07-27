"""M6 Consistency & Consensus Verification Engine (FR-22, specs.md 4.8).

Owned contribution: the LLM only extracts claims; the cross-source agreement
matrix (local NLI), trust-weighted consensus, and consistency_score are
Sentinel's algorithm. Any failure here must leave the pipeline running and
hotspots.consistency_score NULL."""
from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

logger = logging.getLogger("sentinel.consistency")


def _max_domains() -> int:
    return int(os.getenv("SENTINEL_CONSISTENCY_MAX_DOMAINS", "20"))


def _max_claims() -> int:
    return int(os.getenv("SENTINEL_CONSISTENCY_MAX_CLAIMS", "8"))


def _min_prob() -> float:
    return float(os.getenv("SENTINEL_NLI_MIN_PROB", "0.6"))


def _dispute_ratio() -> float:
    return float(os.getenv("SENTINEL_CONSISTENCY_DISPUTE_RATIO", "0.5"))


def render_evidence_text(row: dict) -> str:
    """One factual sentence-or-paragraph per event, from stored fields only."""
    title = (row.get("title") or "").strip()
    if row.get("source_system") == "ACLED":
        notes = (row.get("notes") or "").strip()
        if notes:
            fatalities = row.get("fatalities")
            suffix = f" Fatalities: {int(fatalities)}." if fatalities is not None else ""
            return f"{notes}{suffix}"
        return title
    parts = []
    if row.get("actor1_name"):
        actors = str(row["actor1_name"])
        if row.get("actor2_name"):
            actors += f" vs {row['actor2_name']}"
        parts.append(actors)
    if row.get("goldstein_scale") is not None:
        parts.append(f"Goldstein {row['goldstein_scale']:g}")
    if row.get("avg_tone") is not None:
        parts.append(f"tone {row['avg_tone']:g}")
    if row.get("num_sources") is not None:
        parts.append(f"{int(row['num_sources'])} reports")
    if not parts:
        return title
    structured = "Reported: " + "; ".join(parts) + "."
    return f"{title}. {structured}" if title else structured


def _domain_of(url: str | None) -> str:
    if not url:
        return ""
    return urlparse(url).netloc.lower()


def fetch_hotspot_evidence(conn, hotspot_id: int) -> list[dict]:
    """URL-bearing, non-noise linked events in FR-16 citation order.

    LOCKSTEP CONTRACT: filter + ORDER BY must match
    LLMRepository.fetch_hotspot_articles and api.queries.fetch_hotspot_events,
    so citation_index here equals the SITREP [N] numbering."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT e.event_id, e.title, e.url, e.source_system, e.notes,
                   e.actor1_name, e.actor2_name, e.goldstein_scale, e.avg_tone,
                   e.num_sources, e.fatalities,
                   s.domain, COALESCE(s.trust_score, 0.4) AS trust_score
            FROM event_hotspot eh
            JOIN events e ON e.event_id = eh.event_id
            LEFT JOIN sources s ON s.source_id = e.source_id
            WHERE eh.hotspot_id = %s
              AND NOT COALESCE(eh.is_noise, false)
              AND e.url IS NOT NULL AND e.url <> ''
            ORDER BY e.event_date DESC, e.event_id DESC
            """,
            (hotspot_id,),
        )
        cols = [c[0] for c in cursor.description]
        rows = [dict(zip(cols, r)) for r in cursor.fetchall()]

    evidence: list[dict] = []
    seen_domains: set[str] = set()
    for idx, row in enumerate(rows, start=1):
        domain = row.get("domain") or _domain_of(row.get("url"))
        if domain not in seen_domains and len(seen_domains) >= _max_domains():
            continue
        seen_domains.add(domain)
        evidence.append({
            "event_id": row["event_id"],
            "citation_index": idx,
            "domain": domain,
            "trust_score": float(row["trust_score"]),
            "evidence_text": render_evidence_text(row),
        })
    return evidence
