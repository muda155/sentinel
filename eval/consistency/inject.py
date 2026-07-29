"""Synthetic contradiction injection (FR-22 evaluation harness).

Plants a fabricated contradicting source into real evidence and measures how
often the consensus algorithm flags the claim disputed."""
from __future__ import annotations

from pipeline.consistency import ExtractedClaim, consensus, judge_claims
from pipeline.relevance import similarity_matrix

_FAKE_DOMAIN = "injected.invalid"


def contradiction_premise(claim_text: str) -> str:
    """Phrase a premise the NLI model actually reads as contradicting the claim.

    The wording is load-bearing and was chosen by measurement, not taste. The
    previous template ("CONTRARY: The opposite is reported - not the case that
    X") was rarely read as contradicting at all: the claim appears verbatim and
    a negation cue buried behind a long prefix loses to the lexical overlap. A
    short, front-loaded negation is read correctly instead, at a cosine
    similarity far above SENTINEL_RELEVANCE_MIN_SIM, so the FR-26 gate never
    suppresses it and the harness measures the consensus algorithm rather than
    the phrasing.

    Measured 2026-07-29 over the 40 most recent live claims (deberta NLI,
    all-MiniLM-L6-v2 embedder): planted_premise_detected 95.0% with this
    wording vs 17.5% with the old one; planted-premise cosine min 0.847, mean
    0.915; detection_rate 97.5% with the gate both on and off. The absolute
    numbers move with the claim set in the DB — re-measure with
    ``python -m eval.consistency.inject`` rather than trusting these."""
    return f"It is false that {claim_text}"


def inject_contradiction(evidence: list[dict], claim_text: str) -> list[dict]:
    """Return evidence + one fabricated contradicting row (fresh domain/index)."""
    next_index = max((e["citation_index"] for e in evidence), default=0) + 1
    fake = {
        "event_id": -next_index,          # negative = synthetic, never collides
        "citation_index": next_index,
        "domain": _FAKE_DOMAIN,
        "trust_score": 0.8,
        "evidence_text": contradiction_premise(claim_text),
    }
    return [*evidence, fake]


def detection_rate(cases: list[tuple[list[dict], str]], judge, embedder=None) -> float:
    """Fraction of (evidence, claim_text) cases flagged disputed after injection.

    When ``embedder`` is given the pairs run through the FR-26 relevance gate,
    which is the point of the exercise: the gate must not suppress a genuine
    contradiction. Without it this measures the pre-M8 ungated path."""
    if not cases:
        return 0.0
    detected = 0
    for evidence, claim_text in cases:
        claim = ExtractedClaim(text=claim_text, source_indices=[])
        injected = inject_contradiction(evidence, claim_text)
        sim = None
        if embedder is not None:
            sim = similarity_matrix(
                [claim.text], [e["evidence_text"] for e in injected], embedder
            )
        judgments = judge_claims([claim], injected, judge, sim=sim)
        verdicts = consensus([claim], injected, judgments)
        if verdicts[0].status == "disputed":
            detected += 1
    return detected / len(cases)


def planted_premise_detected(cases: list[tuple[list[dict], str]], judge) -> float:
    """Fraction of injected premises the NLI itself calls a contradiction.

    Validity check on the harness, not on Sentinel. detection_rate only means
    something while this stays high: if the model does not read the planted row
    as contradicting, every dispute it reports came from the *other* evidence
    and the harness is measuring noise. Before the premise wording was fixed it
    sat far below the 0.8 floor main() warns at, while detection_rate still
    printed a healthy-looking number."""
    if not cases:
        return 0.0
    pairs = [(contradiction_premise(text), text) for _evidence, text in cases]
    results = judge.classify_pairs(pairs)
    return sum(1 for rel, _p in results if rel == "contradicts") / len(pairs)


def main() -> int:  # pragma: no cover
    """Run injection over every hotspot that currently has claims."""
    import argparse

    from pipeline.consistency import fetch_hotspot_evidence
    from pipeline.db import get_pooled_connection
    from pipeline.nli import get_judge
    from pipeline.relevance import get_embedder, relevance_enabled

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
    judge = get_judge()
    rate = detection_rate(cases, judge,
                          embedder=get_embedder() if relevance_enabled() else None)
    planted = planted_premise_detected(cases, judge)
    print(f"cases={len(cases)} detection_rate={rate:.2%} "
          f"planted_premise_detected={planted:.2%} gate={'on' if relevance_enabled() else 'off'}")
    if planted < 0.8:
        print("WARNING: the planted premise is not read as contradicting - "
              "detection_rate above is not measuring the consensus algorithm.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
