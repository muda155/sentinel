"""Re-apply consistency_score to hotspots scored before the FR-22(d) change.

One-shot backfill. The engine runs inside generate_sitrep, and
pipeline/workers/llm_worker.py short-circuits on LLMRepository.summary_exists,
so a hotspot that already has a SITREP is never reprocessed: without this,
every score written before the agreement-scaled claim_value stays on the old
formula forever while new hotspots use the new one.

Only hotspots.consistency_score is written. ConsistencyRepository.save is NOT
used: it DELETEs and re-INSERTs claims and resets gated_pairs and
vacuous_claims_dropped to NULL, none of which a rescore should touch.

support and dispute are not stored, so they are recomputed from claim_evidence
under consensus()'s rules (strongest judgment per domain, neutral and
sub-threshold pairs ignored, origin domains barred from corroborating but not
from contradicting). That reconstruction is only trusted where it reproduces
BOTH the stored status and the stored consensus_weight for every claim on the
hotspot -- weight is support + dispute floored at 0.1, so agreeing on it means
agreeing on the split that feeds claim_value. A hotspot with any claim that
fails either check is left alone and reported, never guessed at.

Claims written before migration 023 carry origin_domains NULL, which means
"unknown", not "no origins". A hotspot holding one cannot be reconstructed --
the corroboration rule needs that set -- so it is skipped too.

    python -m scripts.rescore_consistency              # report only
    python -m scripts.rescore_consistency --apply      # write
"""
from __future__ import annotations

import argparse
import logging

from pipeline.consistency import (
    ClaimVerdict,
    _dispute_ratio,
    _min_prob,
    claim_value,
    fetch_hotspot_evidence,
)
from pipeline.db import get_pooled_connection

logger = logging.getLogger("sentinel.rescore_consistency")

# A hotspot is in scope only if it already carries a published score; a NULL
# one was never scored and is the llm-worker's job, not this script's.
SCORED_HOTSPOTS = """
    SELECT DISTINCT c.hotspot_id
    FROM claims c
    JOIN hotspots h ON h.hotspot_id = c.hotspot_id
    WHERE h.consistency_score IS NOT NULL
    ORDER BY 1
"""

CLAIMS_FOR_HOTSPOT = """
    SELECT claim_id, status, consensus_weight, origin_domains
    FROM claims WHERE hotspot_id = %s ORDER BY claim_id
"""

EVIDENCE_FOR_CLAIMS = """
    SELECT claim_id, event_id, relation, probability
    FROM claim_evidence WHERE claim_id = ANY(%s)
"""

STATUS_VALUE = {"corroborated": 1.0, "uncorroborated": 0.5, "disputed": 0.0}
# consensus_weight is a float32 column; the split that produced it is float64.
TOLERANCE = 1e-4


class Unreconstructable(Exception):
    """The stored rows do not reproduce themselves under consensus()'s rules."""


def _recompute(claim, judgments, trust_by_event, domain_by_event):
    """support, dispute and the status they imply, per consensus()."""
    min_prob, ratio = _min_prob(), _dispute_ratio()
    origins = set(claim["origin_domains"])

    best: dict[str, tuple[str, float]] = {}
    for event_id, relation, probability in judgments:
        if probability < min_prob or relation == "neutral":
            continue
        domain = domain_by_event.get(event_id)
        if domain is None:
            # the article list moved under this claim; the weight check below
            # is what turns that into a skip rather than a wrong number
            continue
        current = best.get(domain)
        if current is None or probability > current[1]:
            best[domain] = (relation, probability)

    supporters = {d: p for d, (r, p) in best.items()
                  if r == "supports" and d not in origins}
    contradictors = {d: p for d, (r, p) in best.items() if r == "contradicts"}

    support = sum(trust_by_event[d] * p for d, p in supporters.items())
    dispute = sum(trust_by_event[d] * p for d, p in contradictors.items())

    if contradictors and dispute >= ratio * support:
        status = "disputed"
    elif len(supporters) >= 2:
        status = "corroborated"
    else:
        status = "uncorroborated"
    return support, dispute, status


def rescore_hotspot(conn, hotspot_id: int) -> tuple[float, float]:
    """(old, new) score for one hotspot, or raise Unreconstructable."""
    with conn.cursor() as cursor:
        cursor.execute(CLAIMS_FOR_HOTSPOT, (hotspot_id,))
        claims = [dict(zip(("claim_id", "status", "consensus_weight", "origin_domains"), r))
                  for r in cursor.fetchall()]
        if not claims:
            raise Unreconstructable("no claims")
        if any(c["origin_domains"] is None for c in claims):
            raise Unreconstructable("pre-023 claim with NULL origin_domains")
        cursor.execute(EVIDENCE_FOR_CLAIMS, ([c["claim_id"] for c in claims],))
        by_claim: dict[int, list] = {c["claim_id"]: [] for c in claims}
        for claim_id, event_id, relation, probability in cursor.fetchall():
            by_claim[claim_id].append((event_id, relation, float(probability)))

    evidence = fetch_hotspot_evidence(conn, hotspot_id)
    domain_by_event = {e["event_id"]: e["domain"] for e in evidence}
    trust_by_domain = {e["domain"]: e["trust_score"] for e in evidence}

    old_num = new_num = total_weight = 0.0
    for claim in claims:
        support, dispute, status = _recompute(
            claim, by_claim[claim["claim_id"]], trust_by_domain, domain_by_event,
        )
        weight = float(claim["consensus_weight"])
        if status != claim["status"]:
            raise Unreconstructable(
                f"claim {claim['claim_id']}: status {status} != stored {claim['status']}"
            )
        if abs(max(support + dispute, 0.1) - weight) > TOLERANCE:
            raise Unreconstructable(
                f"claim {claim['claim_id']}: weight {max(support + dispute, 0.1):.6f} "
                f"!= stored {weight:.6f}"
            )
        verdict = ClaimVerdict(text="", status=status, support=support,
                               dispute=dispute, weight=weight, evidence=[],
                               origin_domains=[])
        total_weight += weight
        old_num += weight * STATUS_VALUE[status]
        new_num += weight * claim_value(verdict)

    return 100.0 * old_num / total_weight, 100.0 * new_num / total_weight


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="write the new scores (default: report only)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    conn, pool = get_pooled_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(SCORED_HOTSPOTS)
            hotspot_ids = [r[0] for r in cursor.fetchall()]

        moved, unchanged, skipped = [], 0, []
        for hotspot_id in hotspot_ids:
            try:
                old, new = rescore_hotspot(conn, hotspot_id)
            except Unreconstructable as exc:
                skipped.append((hotspot_id, str(exc)))
                continue
            if abs(new - old) <= TOLERANCE:
                unchanged += 1
                continue
            moved.append((hotspot_id, old, new))
            if args.apply:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE hotspots SET consistency_score = %s WHERE hotspot_id = %s",
                        (new, hotspot_id),
                    )
        if args.apply:
            conn.commit()
    finally:
        pool.return_connection(conn)

    for hotspot_id, old, new in sorted(moved, key=lambda m: m[1] - m[2], reverse=True):
        logger.info("hotspot %-7s %8.3f -> %8.3f  (%+.3f)", hotspot_id, old, new, new - old)
    for hotspot_id, reason in skipped:
        logger.info("skipped hotspot %-7s %s", hotspot_id, reason)
    logger.info("%d candidates: %d moved, %d unchanged, %d skipped%s",
                len(hotspot_ids), len(moved), unchanged, len(skipped),
                "" if args.apply else " (dry run, nothing written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
