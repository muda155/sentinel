"""Clear SITREPs and claims numbered against the pre-collapse citation list.

One-shot repair for deployments that ran before duplicate-URL collapse
(Phase 3, Task 1). Their [N] markers were numbered over an article list that
counted one article several times, so after the collapse they point past the
end of the sources list or at the wrong article.

Deleting the llm_summaries row is what re-arms the hotspot:
LLMRepository.candidate_hotspots gates on NOT EXISTS against that table.
"""
from __future__ import annotations

import argparse
import logging

from pipeline.db import get_pooled_connection

logger = logging.getLogger("sentinel.invalidate_stale_sitreps")

AFFECTED_HOTSPOTS = """
    SELECT DISTINCT eh.hotspot_id
    FROM event_hotspot eh
    JOIN events e ON e.event_id = eh.event_id
    WHERE NOT COALESCE(eh.is_noise, false)
      AND e.url IS NOT NULL AND e.url <> ''
    GROUP BY eh.hotspot_id, e.url
    HAVING count(*) > 1
"""


def find_affected(conn) -> list[int]:
    with conn.cursor() as cur:
        cur.execute(AFFECTED_HOTSPOTS)
        return sorted({int(r[0]) for r in cur.fetchall()})


def invalidate(conn, hotspot_ids: list[int]) -> dict[str, int]:
    if not hotspot_ids:
        return {"summaries": 0, "claims": 0, "scores": 0}
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM llm_summaries WHERE hotspot_id = ANY(%s)", (hotspot_ids,)
        )
        summaries = cur.rowcount
        cur.execute("DELETE FROM claims WHERE hotspot_id = ANY(%s)", (hotspot_ids,))
        claims = cur.rowcount
        cur.execute(
            "UPDATE hotspots SET consistency_score = NULL WHERE hotspot_id = ANY(%s)",
            (hotspot_ids,),
        )
        scores = cur.rowcount
    conn.commit()
    return {"summaries": summaries, "claims": claims, "scores": scores}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="perform the deletion (default is a dry run)",
    )
    args = parser.parse_args()

    # get_pooled_connection() returns (conn, pool) — the pool is how the
    # connection gets returned. Never unpack it as a bare connection.
    conn, pool = get_pooled_connection()
    try:
        affected = find_affected(conn)
        logger.info("hotspots with duplicate article URLs: %d", len(affected))
        if not args.apply:
            logger.info("dry run — re-run with --apply to invalidate")
            return 0
        counts = invalidate(conn, affected)
        logger.info(
            "deleted %d summaries, %d claims; nulled %d consistency_scores",
            counts["summaries"], counts["claims"], counts["scores"],
        )
    finally:
        pool.return_connection(conn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
