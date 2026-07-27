"""Export claims to JSONL for human gold-set labeling (FR-22 evaluation).

Each line is one claim with null label fields; labelers set label_claim_ok
(claim is faithful+atomic) and label_status_ok (status verdict is correct)."""
from __future__ import annotations

import argparse
import json
import sys

from pipeline.db import get_pooled_connection


def export(conn, limit: int, out) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT c.hotspot_id, c.claim_text, c.status,
                      COALESCE(json_agg(json_build_object(
                          'event_id', ce.event_id, 'relation', ce.relation)
                      ) FILTER (WHERE ce.claim_id IS NOT NULL), '[]')
               FROM claims c
               LEFT JOIN claim_evidence ce ON ce.claim_id = c.claim_id
               GROUP BY c.claim_id
               ORDER BY c.hotspot_id DESC, c.claim_id
               LIMIT %s""",
            (limit,),
        )
        count = 0
        for hotspot_id, text, status, evidence in cur.fetchall():
            out.write(json.dumps({
                "hotspot_id": hotspot_id, "claim_text": text, "status": status,
                "evidence": evidence,
                "label_claim_ok": None, "label_status_ok": None,
            }) + "\n")
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Export gold-set JSONL")
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()
    conn, pool = get_pooled_connection()
    try:
        count = export(conn, args.limit, sys.stdout)
    finally:
        pool.return_connection(conn)
    print(f"exported {count} claims", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
