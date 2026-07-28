"""M6 Consistency & Consensus Verification Engine (FR-22, specs.md 4.8).

Owned contribution: the LLM only extracts claims; the cross-source agreement
matrix (local NLI), trust-weighted consensus, and consistency_score are
Sentinel's algorithm. Any failure here must leave the pipeline running and
hotspots.consistency_score NULL."""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from pydantic import BaseModel, ValidationError

from pipeline.llm_verifier import _extract_json, call_llm_raw
from pipeline.relevance import min_sim

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
    """One representative (most recent) row per unique domain, FR-16 order.

    LOCKSTEP CONTRACT: filter + ORDER BY must match
    LLMRepository.fetch_hotspot_articles and api.queries.fetch_hotspot_events;
    citation_index is the row's position in the FULL article list, so [N]
    markers keep resolving even though duplicate-domain rows are dropped.
    Deduping per domain matches spec 4.8 FR-22(b) ("over unique domains") and
    keeps the extraction prompt small enough for NIM's latency budget."""
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
        if domain in seen_domains:
            continue
        if len(seen_domains) >= _max_domains():
            break
        seen_domains.add(domain)
        evidence.append({
            "event_id": row["event_id"],
            "citation_index": idx,
            "domain": domain,
            "trust_score": float(row["trust_score"]),
            "evidence_text": render_evidence_text(row),
        })
    return evidence


class ExtractedClaim(BaseModel):
    text: str
    source_indices: list[int] = []


class _ClaimExtraction(BaseModel):
    claims: list[ExtractedClaim] = []


def build_claims_prompt(evidence: list[dict]) -> str:
    lines = [
        "Act as an intelligence analyst. Below are numbered evidence items about one "
        "geographic hotspot, each from a different report.",
        (
            f"Extract at most {_max_claims()} atomic factual claims stated by the evidence. "
            "Rules: each claim MUST be a complete English sentence with a subject and a "
            "verb describing a concrete event or situation (e.g., 'Military forces "
            "advanced north of the city.'). Never output bare names, actor pairings, or "
            "sentence fragments. Ignore numeric metadata such as tone scores, Goldstein "
            "scale values, and report counts - they are signals, not claims. If the "
            'evidence contains no verifiable factual statements, return {"claims": []}. '
            "For each claim list the evidence numbers that assert it."
        ),
        'Output JSON only, no prose outside it: '
        '{"claims": [{"text": str, "source_indices": [int]}]}',
        "",
        "Evidence:",
    ]
    for item in evidence:
        lines.append(f"[{item['citation_index']}] {item['evidence_text']}")
    return "\n".join(lines)


def _default_llm(prompt: str) -> tuple[str, str]:
    return call_llm_raw(
        prompt,
        endpoint=os.getenv("NVIDIA_NIM_ENDPOINT", ""),
        api_key=os.getenv("NVIDIA_NIM_API_KEY", ""),
        model=os.getenv("NVIDIA_NIM_MODEL", "meta/llama-3.3-70b-instruct"),
        ollama_endpoint=os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434"),
    )


def _min_claim_words() -> int:
    return int(os.getenv("SENTINEL_CONSISTENCY_MIN_CLAIM_WORDS", "4"))


_LOWERCASE_WORD = re.compile(r"[a-z]{3,}")


def is_valid_claim(text: str) -> bool:
    """Reject degenerate extractions (bare actor names, ALL-CAPS fragments).

    A claim must have at least SENTINEL_CONSISTENCY_MIN_CLAIM_WORDS words and
    one real lowercase word - GDELT-derived fragments like 'A US vs IRAN' or
    'GROUND TROOP' fail both a sentence reading and NLI judging, and would
    otherwise be scored as all-disputed noise."""
    words = text.split()
    return len(words) >= _min_claim_words() and bool(_LOWERCASE_WORD.search(text))


def extract_claims(evidence: list[dict], *, llm=None) -> list[ExtractedClaim]:
    """One LLM call -> validated atomic claims. Empty list on any parse failure
    or when every extracted claim is degenerate (engine then skips, score NULL)."""
    llm = llm or _default_llm
    content, _model = llm(build_claims_prompt(evidence))
    try:
        parsed = _ClaimExtraction(**_extract_json(content))
    except (ValueError, ValidationError) as exc:
        logger.warning("Claim extraction unparseable, skipping engine: %s", exc)
        return []
    valid = {item["citation_index"] for item in evidence}
    claims = []
    for claim in parsed.claims:
        if not is_valid_claim(claim.text):
            logger.info("Dropping degenerate claim: %r", claim.text)
            continue
        claim.source_indices = [i for i in claim.source_indices if i in valid]
        claims.append(claim)
        if len(claims) >= _max_claims():
            break
    return claims


def _normalised_claim_key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold().rstrip(".!?")


def dedupe_claims(claims: list[ExtractedClaim]) -> list[ExtractedClaim]:
    """Collapse claims with identical normalised text (FR-26).

    Without this, a repeated claim is scored once per copy: hotspot 24795 held
    three "Russia is mentioned" rows, each contributing its own weight."""
    by_key: dict[str, ExtractedClaim] = {}
    indices: dict[str, set[int]] = {}
    for claim in claims:
        key = _normalised_claim_key(claim.text)
        if key not in by_key:
            by_key[key] = claim
            indices[key] = set()
        indices[key].update(claim.source_indices)
    return [
        ExtractedClaim(text=claim.text, source_indices=sorted(indices[key]))
        for key, claim in by_key.items()
    ]


@dataclass
class EvidenceJudgment:
    event_id: int
    citation_index: int
    domain: str
    relation: str
    probability: float


@dataclass
class ClaimVerdict:
    text: str
    status: str            # corroborated | uncorroborated | disputed
    support: float
    dispute: float
    weight: float
    evidence: list[EvidenceJudgment] = field(default_factory=list)


def judge_claims(claims, evidence, judge, *, sim=None, threshold=None) -> list[list[EvidenceJudgment]]:
    """NLI-classify every (evidence premise, claim hypothesis) pair, batched.

    When ``sim`` is supplied, only pairs at or above ``threshold`` reach the
    model (FR-26). An MNLI cross-encoder assumes premise and hypothesis describe
    the same scene, so off-scene pairs come back "contradiction" by
    construction; gating is what stops unrelated stories disputing each other.

    A judgment is still emitted for every pair — gated ones as neutral/0.0 — so
    claim_evidence persistence and the FR-16 citation contract are unchanged."""
    limit = min_sim() if threshold is None else threshold
    pairs: list[tuple[str, str]] = []
    positions: list[tuple[int, int]] = []
    for ci, claim in enumerate(claims):
        for ei, item in enumerate(evidence):
            if sim is not None and float(sim[ci][ei]) < limit:
                continue
            pairs.append((item["evidence_text"], claim.text))
            positions.append((ci, ei))

    results = judge.classify_pairs(pairs) if pairs else []
    judged = dict(zip(positions, results))

    judgments: list[list[EvidenceJudgment]] = []
    for ci, _claim in enumerate(claims):
        row = []
        for ei, item in enumerate(evidence):
            relation, prob = judged.get((ci, ei), ("neutral", 0.0))
            row.append(EvidenceJudgment(
                event_id=item["event_id"], citation_index=item["citation_index"],
                domain=item["domain"], relation=relation, probability=prob,
            ))
        judgments.append(row)
    return judgments


def count_gated_pairs(sim, threshold=None) -> int:
    """How many (claim, evidence) pairs the gate suppresses. Persisted for tuning."""
    if sim is None:
        return 0
    limit = min_sim() if threshold is None else threshold
    return int(sum(
        1
        for row in sim
        for value in row
        if float(value) < limit
    ))


def consensus(claims, evidence, judgments) -> list[ClaimVerdict]:
    """Trust-weighted per-claim consensus over unique domains (FR-22).

    Per domain, the strongest judgment wins. A claim's origin domains (the
    sources that asserted it) never count toward corroboration, but may
    contradict. Pairs below SENTINEL_NLI_MIN_PROB are ignored entirely."""
    min_prob = _min_prob()
    ratio = _dispute_ratio()
    trust_by_domain = {item["domain"]: item["trust_score"] for item in evidence}
    domain_by_index = {item["citation_index"]: item["domain"] for item in evidence}

    verdicts: list[ClaimVerdict] = []
    for claim, row in zip(claims, judgments):
        origin_domains = {domain_by_index[i] for i in claim.source_indices
                          if i in domain_by_index}
        best: dict[str, EvidenceJudgment] = {}
        for judgment in row:
            if judgment.probability < min_prob or judgment.relation == "neutral":
                continue
            current = best.get(judgment.domain)
            if current is None or judgment.probability > current.probability:
                best[judgment.domain] = judgment

        supporters = {d: j for d, j in best.items()
                      if j.relation == "supports" and d not in origin_domains}
        contradictors = {d: j for d, j in best.items() if j.relation == "contradicts"}

        support = sum(trust_by_domain.get(d, 0.4) * j.probability
                      for d, j in supporters.items())
        dispute = sum(trust_by_domain.get(d, 0.4) * j.probability
                      for d, j in contradictors.items())

        if contradictors and dispute >= ratio * support:
            status = "disputed"
        elif len(supporters) >= 2:
            status = "corroborated"
        else:
            status = "uncorroborated"

        verdicts.append(ClaimVerdict(
            text=claim.text, status=status, support=support, dispute=dispute,
            weight=max(support + dispute, 0.1), evidence=row,
        ))
    return verdicts


_STATUS_VALUE = {"corroborated": 1.0, "uncorroborated": 0.5, "disputed": 0.0}


def hotspot_consistency_score(verdicts: list[ClaimVerdict]) -> float | None:
    """consistency_score = 100 * sum(w*v) / sum(w); None when no claims."""
    if not verdicts:
        return None
    total_weight = sum(v.weight for v in verdicts)
    weighted = sum(v.weight * _STATUS_VALUE[v.status] for v in verdicts)
    return 100.0 * weighted / total_weight


@dataclass
class EngineResult:
    verdicts: list[ClaimVerdict]
    score: float | None
    insufficient_sources: bool


class ConsistencyRepository:
    def __init__(self, conn) -> None:
        self._conn = conn

    def save(self, hotspot_id: int, verdicts: list[ClaimVerdict],
             score: float | None) -> None:
        with self._conn.cursor() as cursor:
            cursor.execute("DELETE FROM claims WHERE hotspot_id = %s", (hotspot_id,))
            for verdict in verdicts:
                cursor.execute(
                    """INSERT INTO claims (hotspot_id, claim_text, status, consensus_weight)
                       VALUES (%s, %s, %s, %s) RETURNING claim_id""",
                    (hotspot_id, verdict.text, verdict.status, verdict.weight),
                )
                claim_id = cursor.fetchone()[0]
                for judgment in verdict.evidence:
                    cursor.execute(
                        """INSERT INTO claim_evidence (claim_id, event_id, relation, probability)
                           VALUES (%s, %s, %s, %s)
                           ON CONFLICT (claim_id, event_id) DO NOTHING""",
                        (claim_id, judgment.event_id, judgment.relation,
                         judgment.probability),
                    )
            cursor.execute(
                "UPDATE hotspots SET consistency_score = %s WHERE hotspot_id = %s",
                (score, hotspot_id),
            )
        self._conn.commit()


def run_consistency_engine(conn, hotspot_id: int, *, judge=None,
                           llm=None) -> EngineResult | None:
    """6a: evidence -> claims -> NLI matrix -> consensus -> persist.

    Uses a savepoint so any partial-DB rollback does not affect the caller's
    transaction. Returns None on any failure or empty input; NEVER raises (the
    pipeline and SITREP fallback depend on that)."""
    with conn.cursor() as cur:
        cur.execute("SAVEPOINT sp_consistency")
    try:
        evidence = fetch_hotspot_evidence(conn, hotspot_id)
        if not evidence:
            return None
        claims = extract_claims(evidence, llm=llm)
        if not claims:
            return None
        if judge is None:
            from pipeline.nli import get_judge
            judge = get_judge()
        judgments = judge_claims(claims, evidence, judge)
        verdicts = consensus(claims, evidence, judgments)
        score = hotspot_consistency_score(verdicts)
        insufficient = len({e["domain"] for e in evidence}) < 2
        ConsistencyRepository(conn).save(hotspot_id, verdicts, score)
        return EngineResult(verdicts=verdicts, score=score,
                            insufficient_sources=insufficient)
    except Exception as exc:
        logger.warning("Consistency engine skipped for hotspot %s: %s",
                       hotspot_id, exc)
        try:
            with conn.cursor() as cur:
                cur.execute("ROLLBACK TO SAVEPOINT sp_consistency")
        except Exception:
            pass
        return None


def main() -> int:
    import argparse

    from pipeline.db import get_pooled_connection

    parser = argparse.ArgumentParser(description="Run the consistency engine on one hotspot")
    parser.add_argument("--hotspot-id", type=int, required=True)
    args = parser.parse_args()
    conn, pool = get_pooled_connection()
    try:
        result = run_consistency_engine(conn, args.hotspot_id)
    finally:
        pool.return_connection(conn)
    if result is None:
        print("engine skipped (no evidence/claims or NLI unavailable)")
        return 1
    print(f"score={result.score:.1f} claims={len(result.verdicts)} "
          f"insufficient_sources={result.insufficient_sources}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
