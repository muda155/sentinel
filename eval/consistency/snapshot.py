"""Atomic snapshot of everything the consistency_score depends on.

The pipeline writes to `claims`, `claim_evidence` and `hotspots` on every tick,
so two formula variants measured minutes apart are measured on two different
datasets and the difference between them is unattributable. Every read here
happens inside ONE `REPEATABLE READ` transaction, so the four files describe a
single instant, and every variant in `weight_backtest.py` is scored against
that same instant.

Written files (JSONL, one object per line, in `--out` directory):
  claims.jsonl        claim_id, hotspot_id, claim_text, status,
                      consensus_weight, origin_domains (null = pre-023)
  claim_evidence.jsonl  claim_id, event_id, relation, probability
  event_domain.jsonl  event_id -> domain, trust_score, resolved exactly as
                      consistency.fetch_hotspot_evidence resolves them
  hotspots.jsonl      hotspot_id, consistency_score, conf_score, ...
  meta.json           row counts + capture timestamp
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from pipeline.db import get_pooled_connection

CLAIMS_SQL = """
    SELECT claim_id, hotspot_id, claim_text, status, consensus_weight,
           origin_domains
    FROM claims
    ORDER BY claim_id
"""

CLAIM_EVIDENCE_SQL = """
    SELECT ce.claim_id, ce.event_id, ce.relation, ce.probability
    FROM claim_evidence ce
    ORDER BY ce.claim_id, ce.event_id
"""

# COALESCE(s.trust_score, 0.4) and `s.domain or urlparse(url).netloc` mirror
# consistency.fetch_hotspot_evidence exactly; a different default here would
# reproduce a score the engine never computed.
EVENT_DOMAIN_SQL = """
    SELECT e.event_id, s.domain, e.url, COALESCE(s.trust_score, 0.4) AS trust_score
    FROM events e
    LEFT JOIN sources s ON s.source_id = e.source_id
    WHERE e.event_id IN (SELECT DISTINCT event_id FROM claim_evidence)
"""

# cell_convergence_score, not hotspots.convergence_score: the denormalised copy
# on hotspots is NULL for every row (0 of 1321 populated on 2026-08-20), so the
# convergence figure has to come from grid_cells through cell_id. Both columns
# are dumped so a reader can see the copy is empty rather than assume it.
# hotspots.convergence_score is NULL on every live row (0 of 1321 populated on
# 2026-08-20): the two-stage worker path stores the score on the GRID CELL and
# the API reads COALESCE(g.convergence_score, h.convergence_score, 0). Reading
# only the hotspot column yields an empty sample and a correlation of None, so
# the cell value is joined in as cell_convergence_score.
HOTSPOTS_SQL = """
    SELECT h.hotspot_id, h.name, h.consistency_score, h.conf_score,
           h.convergence_score, g.convergence_score AS cell_convergence_score,
           h.event_count, h.unique_sources, h.gated_pairs, h.vacuous_claims_dropped
    FROM hotspots h
    LEFT JOIN grid_cells g ON g.cell_id = h.cell_id
    ORDER BY h.hotspot_id
"""


def _domain_of(url: str | None) -> str:
    if not url:
        return ""
    return urlparse(url).netloc.lower()


def _dump(cursor, sql: str, path: Path) -> int:
    cursor.execute(sql)
    cols = [c[0] for c in cursor.description]
    count = 0
    with path.open("w", encoding="utf-8") as fh:
        for row in cursor.fetchall():
            fh.write(json.dumps(dict(zip(cols, row)), default=str) + "\n")
            count += 1
    return count


def capture(conn, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        counts = {
            "claims": _dump(cur, CLAIMS_SQL, out_dir / "claims.jsonl"),
            "claim_evidence": _dump(cur, CLAIM_EVIDENCE_SQL, out_dir / "claim_evidence.jsonl"),
            "hotspots": _dump(cur, HOTSPOTS_SQL, out_dir / "hotspots.jsonl"),
        }
        cur.execute(EVENT_DOMAIN_SQL)
        rows = cur.fetchall()
        with (out_dir / "event_domain.jsonl").open("w", encoding="utf-8") as fh:
            for event_id, domain, url, trust in rows:
                fh.write(json.dumps({
                    "event_id": event_id,
                    "domain": domain or _domain_of(url),
                    "trust_score": float(trust),
                }) + "\n")
        counts["event_domain"] = len(rows)
        cur.execute("COMMIT")

    meta = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "counts": counts,
        "nli_min_prob": float(os.getenv("SENTINEL_NLI_MIN_PROB", "0.6")),
        "dispute_ratio": float(os.getenv("SENTINEL_CONSISTENCY_DISPUTE_RATIO", "0.5")),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump an atomic consistency snapshot")
    parser.add_argument("--out", required=True, help="output directory")
    args = parser.parse_args()
    conn, pool = get_pooled_connection()
    try:
        meta = capture(conn, Path(args.out))
    finally:
        pool.return_connection(conn)
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
