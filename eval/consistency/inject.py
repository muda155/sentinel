"""Synthetic contradiction injection (FR-22 evaluation harness).

Plants a fabricated contradicting source into real evidence and measures how
often the consensus algorithm flags the claim disputed."""
from __future__ import annotations

from pipeline.consistency import ExtractedClaim, consensus, judge_claims

_FAKE_DOMAIN = "injected.invalid"


def inject_contradiction(evidence: list[dict], claim_text: str) -> list[dict]:
    """Return evidence + one fabricated contradicting row (fresh domain/index)."""
    next_index = max((e["citation_index"] for e in evidence), default=0) + 1
    fake = {
        "event_id": -next_index,          # negative = synthetic, never collides
        "citation_index": next_index,
        "domain": _FAKE_DOMAIN,
        "trust_score": 0.8,
        "evidence_text": f"CONTRARY: The opposite is reported - not the case that {claim_text}",
    }
    return [*evidence, fake]


def detection_rate(cases: list[tuple[list[dict], str]], judge) -> float:
    """Fraction of (evidence, claim_text) cases flagged disputed after injection."""
    if not cases:
        return 0.0
    detected = 0
    for evidence, claim_text in cases:
        claim = ExtractedClaim(text=claim_text, source_indices=[])
        injected = inject_contradiction(evidence, claim_text)
        verdicts = consensus([claim], injected, judge_claims([claim], injected, judge))
        if verdicts[0].status == "disputed":
            detected += 1
    return detected / len(cases)


def main() -> int:  # pragma: no cover
    """Run injection over every hotspot that currently has claims."""
    import argparse

    from pipeline.consistency import fetch_hotspot_evidence
    from pipeline.db import get_pooled_connection
    from pipeline.nli import get_judge

    parser = argparse.ArgumentParser(description="Contradiction-injection evaluation")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    conn, pool = get_pooled_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT DISTINCT c.hotspot_id, c.claim_text FROM claims c
                   ORDER BY c.hotspot_id DESC LIMIT %s""",
                (args.limit,),
            )
            rows = cur.fetchall()
        cases = [(fetch_hotspot_evidence(conn, hid), text) for hid, text in rows]
        cases = [c for c in cases if c[0]]
    finally:
        pool.return_connection(conn)
    if not cases:
        print("no claims in DB - run the pipeline first")
        return 1
    rate = detection_rate(cases, get_judge())
    print(f"cases={len(cases)} detection_rate={rate:.2%}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
