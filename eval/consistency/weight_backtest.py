"""Offline backtest of consistency_score weighting formulas (FR-22 step d).

`claim_evidence` persists the FULL NLI judgment matrix — including `neutral`
rows and pairs below `SENTINEL_NLI_MIN_PROB` — so per-claim `support` and
`dispute` can be recomputed exactly from a snapshot, with no LLM call, no NLI
model and no GPU. Every candidate formula is therefore scored on identical
inputs.

The bug under test: `consensus()` sets `weight = max(support + dispute, 0.1)`
while `hotspot_consistency_score()` multiplies that weight by a status constant.
A dispute vote thus RAISES the weight of a claim whose status it failed to
change, so a contested claim outvotes a clean one of equal support.

Run `eval.consistency.snapshot` first; this module never touches the database.

    python -m eval.consistency.snapshot --out /tmp/snap
    python -m eval.consistency.weight_backtest --snapshot /tmp/snap
"""
from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

STATUS_VALUE = {"corroborated": 1.0, "uncorroborated": 0.5, "disputed": 0.0}
WEIGHT_FLOOR = 0.1
DEFAULT_TRUST = 0.4


def _min_prob() -> float:
    return float(os.getenv("SENTINEL_NLI_MIN_PROB", "0.6"))


def _dispute_ratio() -> float:
    return float(os.getenv("SENTINEL_CONSISTENCY_DISPUTE_RATIO", "0.5"))


@dataclass
class Outcome:
    """One claim's reconstructed consensus, before any weighting formula."""
    claim_id: int
    hotspot_id: int
    text: str
    status: str
    support: float
    dispute: float
    supporters: int
    contradictors: int
    stored_weight: float | None


# --- variants ---------------------------------------------------------------
# Each variant is (weight(outcome), value(outcome)); the hotspot score is
# 100 * sum(w*v) / sum(w), exactly as in hotspot_consistency_score().


def _agreement(o: Outcome) -> float | None:
    """support / (support + dispute); None when no judgment survived at all."""
    total = o.support + o.dispute
    if total <= 0.0:
        return None
    return o.support / total


def w_old(o: Outcome) -> float:
    return max(o.support + o.dispute, WEIGHT_FLOOR)


def w_support_only(o: Outcome) -> float:
    return max(o.support, WEIGHT_FLOOR)


def w_penalised(o: Outcome) -> float:
    return max(o.support - o.dispute, WEIGHT_FLOOR)


def v_status(o: Outcome) -> float:
    return STATUS_VALUE[o.status]


def v_agreement(o: Outcome) -> float:
    # 0/0 is the modal case here, not an edge case: a claim whose every NLI pair
    # was gated or fell below min_prob has no evidence either way. It is exactly
    # the "uncorroborated" case, so it keeps 0.5 rather than being scored 0 (an
    # accusation of contradiction) or 1 (an unearned corroboration).
    a = _agreement(o)
    return STATUS_VALUE["uncorroborated"] if a is None else a


def _v_capped(k: float):
    def value(o: Outcome) -> float:
        a = _agreement(o)
        base = STATUS_VALUE[o.status]
        if a is None:
            return base
        return base * (1.0 - k * (1.0 - a))
    return value


VARIANTS: dict[str, tuple] = {
    "old":        (w_old, v_status),
    "A_support_weight":   (w_support_only, v_status),
    "B_agreement_value":  (w_old, v_agreement),
    "C_capped_k1":        (w_old, _v_capped(1.0)),
    "C_capped_k0.5":      (w_old, _v_capped(0.5)),
    "D_weight_minus":     (w_penalised, v_status),
}

# What pipeline/consistency.py computes today (chosen 2026-08-20). "old" is
# kept because rows written before the change still carry its output, so
# verify_reproduction has to be able to identify which formula wrote a score.
SHIPPED_VARIANT = "C_capped_k1"
PRE_2026_08_20_VARIANT = "old"


def hotspot_score(outcomes: list[Outcome], variant: str) -> float | None:
    weight_fn, value_fn = VARIANTS[variant]
    if not outcomes:
        return None
    total = sum(weight_fn(o) for o in outcomes)
    if total <= 0:
        return None
    return 100.0 * sum(weight_fn(o) * value_fn(o) for o in outcomes) / total


# --- reconstruction ---------------------------------------------------------


def load_snapshot(path: Path) -> dict:
    def rows(name):
        with (path / name).open(encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    domains = {r["event_id"]: r for r in rows("event_domain.jsonl")}
    evidence: dict[int, list[dict]] = {}
    for r in rows("claim_evidence.jsonl"):
        evidence.setdefault(r["claim_id"], []).append(r)
    return {
        "claims": rows("claims.jsonl"),
        "evidence": evidence,
        "event_domain": domains,
        "hotspots": {r["hotspot_id"]: r for r in rows("hotspots.jsonl")},
        "meta": json.loads((path / "meta.json").read_text(encoding="utf-8")),
    }


def reconstruct(claim: dict, evidence: list[dict], event_domain: dict) -> Outcome:
    """Replay consensus() for one claim: best judgment per DOMAIN, not per event.

    consistency.consensus() reduces per domain and looks trust up per domain, so
    reducing per event would double-count any two events sharing an outlet."""
    min_prob = _min_prob()
    ratio = _dispute_ratio()
    origins = set(claim["origin_domains"] or [])

    best: dict[str, dict] = {}
    for judgment in evidence:
        prob = judgment["probability"]
        if prob is None or prob < min_prob or judgment["relation"] == "neutral":
            continue
        meta = event_domain.get(judgment["event_id"])
        domain = meta["domain"] if meta else ""
        current = best.get(domain)
        if current is None or prob > current["probability"]:
            best[domain] = {**judgment, "domain": domain,
                            "trust": meta["trust_score"] if meta else DEFAULT_TRUST}

    support = dispute = 0.0
    supporters = contradictors = 0
    for domain, j in best.items():
        mass = j["trust"] * j["probability"]
        if j["relation"] == "supports":
            if domain in origins:
                continue
            support += mass
            supporters += 1
        elif j["relation"] == "contradicts":
            dispute += mass
            contradictors += 1

    if contradictors and dispute >= ratio * support:
        status = "disputed"
    elif supporters >= 2:
        status = "corroborated"
    else:
        status = "uncorroborated"

    return Outcome(
        claim_id=claim["claim_id"], hotspot_id=claim["hotspot_id"],
        text=claim["claim_text"], status=status, support=support, dispute=dispute,
        supporters=supporters, contradictors=contradictors,
        stored_weight=claim.get("consensus_weight"),
    )


def build_outcomes(snap: dict) -> tuple[dict[int, list[Outcome]], dict]:
    """Group reconstructed outcomes by hotspot, dropping unverifiable ones.

    origin_domains IS NULL means "written before migration 023" — the claim's
    own asserting domains are unknown, so its corroboration cannot be
    reproduced (treating NULL as an empty set would let a source corroborate
    itself and inflate every such claim). Migration 023's contract is that NULL
    is unverifiable, so any hotspot holding one is dropped whole: keeping its
    other claims would silently change the denominator instead of the score."""
    by_hotspot: dict[int, list[Outcome]] = {}
    unverifiable_claims = 0
    tainted: set[int] = set()
    status_mismatch = 0
    weight_mismatch = 0

    for claim in snap["claims"]:
        hid = claim["hotspot_id"]
        if claim["origin_domains"] is None:
            unverifiable_claims += 1
            tainted.add(hid)
            continue
        o = reconstruct(claim, snap["evidence"].get(claim["claim_id"], []),
                        snap["event_domain"])
        if o.status != claim["status"]:
            status_mismatch += 1
        if o.stored_weight is not None and abs(w_old(o) - o.stored_weight) > 1e-6:
            weight_mismatch += 1
        by_hotspot.setdefault(hid, []).append(o)

    kept = {h: v for h, v in by_hotspot.items() if h not in tainted}
    diagnostics = {
        "claims_total": len(snap["claims"]),
        "claims_unverifiable_null_origin": unverifiable_claims,
        "hotspots_with_claims": len(by_hotspot),
        "hotspots_dropped_tainted": len(by_hotspot) - len(kept),
        "hotspots_measured": len(kept),
        "claims_measured": sum(len(v) for v in kept.values()),
        "status_reconstruction_mismatch": status_mismatch,
        "weight_reconstruction_mismatch": weight_mismatch,
    }
    return kept, diagnostics


# --- statistics -------------------------------------------------------------


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    return pearson(_ranks(xs), _ranks(ys))


def describe(scores: list[float]) -> dict:
    if not scores:
        return {}
    ordered = sorted(scores)
    n = len(ordered)
    median = ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2
    hist = [0] * 11  # 10-point buckets; index 10 holds exactly 100.0
    for s in scores:
        hist[min(int(s // 10), 10)] += 1
    return {
        "n": n, "min": ordered[0], "median": median,
        "mean": sum(ordered) / n, "max": ordered[-1],
        "histogram_10pt": hist,
    }


# FR-13 defines green >70 / yellow 40-70 / grey <40 for conf_score ONLY.
# frontend-next renders consistency_score as a bare number with no bucketing,
# so this is a BORROWED yardstick for comparing variants, not a UI contract.
def fr13_bucket(score: float) -> str:
    if score > 70:
        return "green"
    if score >= 40:
        return "yellow"
    return "grey"


def decile(score: float) -> int:
    return min(int(score // 10), 10)


# --- the property under test ------------------------------------------------


def contribution(o: Outcome, variant: str) -> float:
    """Numerator mass w*v — the project owner's framing of 'contribution'."""
    weight_fn, value_fn = VARIANTS[variant]
    return weight_fn(o) * value_fn(o)


def reference_score(o: Outcome, variant: str, ref_weight: float = 1.0,
                    ref_value: float = 0.5) -> float:
    """Score of a synthetic hotspot = this claim + one fixed neutral claim.

    w*v alone is not the whole contribution: the same weight also enters the
    denominator, so a variant can shrink the numerator and the denominator
    together and leave the score unmoved. Mixing against a fixed reference
    claim measures what the claim actually does to a hotspot's score."""
    weight_fn, value_fn = VARIANTS[variant]
    w, v = weight_fn(o), value_fn(o)
    return 100.0 * (w * v + ref_weight * ref_value) / (w + ref_weight)


def clean_twin(o: Outcome) -> Outcome:
    """The same claim with its dispute mass removed, status held constant.

    Real pairs are never perfectly matched on support, so a pair test always
    leaves a residual. The counterfactual has zero residual by construction:
    support, status and everything else the formula reads are literally the
    same object, and dispute is the only thing that moved. Status is held
    fixed on purpose — the question is what the WEIGHTING does with a dispute
    vote that failed to change the classification, which is precisely the case
    `dispute >= ratio * support` lets through."""
    return Outcome(
        claim_id=o.claim_id, hotspot_id=o.hotspot_id, text=o.text,
        status=o.status, support=o.support, dispute=0.0,
        supporters=o.supporters, contradictors=0, stored_weight=None,
    )


def counterfactual_check(outcomes: list[Outcome], variant: str) -> dict:
    """For every claim carrying dispute mass: does removing that dispute raise
    its contribution? It must — the disputed version has to contribute less."""
    rewarded = penalised = tied = 0
    ref_rewarded = ref_penalised = ref_tied = 0
    examples = []
    for o in outcomes:
        if o.dispute <= 0:
            continue
        twin = clean_twin(o)
        d = contribution(o, variant) - contribution(twin, variant)
        if d > 1e-9:
            rewarded += 1
        elif d < -1e-9:
            penalised += 1
        else:
            tied += 1
        r = reference_score(o, variant) - reference_score(twin, variant)
        if r > 1e-9:
            ref_rewarded += 1
        elif r < -1e-9:
            ref_penalised += 1
        else:
            ref_tied += 1
        if len(examples) < 4:
            examples.append({
                "claim_id": o.claim_id, "status": o.status,
                "support": round(o.support, 4), "dispute": round(o.dispute, 4),
                "wv_with_dispute": round(contribution(o, variant), 4),
                "wv_without_dispute": round(contribution(twin, variant), 4),
                "refmix_with_dispute": round(reference_score(o, variant), 3),
                "refmix_without_dispute": round(reference_score(twin, variant), 3),
            })
    n = rewarded + penalised + tied
    return {
        "claims_tested": n,
        "numerator_dispute_rewarded": rewarded,
        "numerator_dispute_penalised": penalised,
        "numerator_unchanged": tied,
        "refmix_dispute_rewarded": ref_rewarded,
        "refmix_dispute_penalised": ref_penalised,
        "refmix_unchanged": ref_tied,
        "violation_rate": (rewarded + ref_rewarded) / max(2 * n, 1),
        "examples": examples,
    }


def dispute_sweep(variant: str, status: str = "corroborated", support: float = 2.0,
                  steps=(0.0, 0.25, 0.5, 1.0, 2.0, 4.0)) -> list[dict]:
    """Contribution of one synthetic claim as dispute mass grows. Both columns
    must be non-increasing down the table for the variant to be admissible."""
    out = []
    for d in steps:
        o = Outcome(claim_id=0, hotspot_id=0, text="", status=status,
                    support=support, dispute=d, supporters=3,
                    contradictors=0 if d == 0 else 1, stored_weight=None)
        out.append({"dispute": d,
                    "w_times_v": round(contribution(o, variant), 4),
                    "refmix_score": round(reference_score(o, variant), 3)})
    return out


def dispute_pairs(outcomes: list[Outcome], *, tol: float = 0.05,
                  min_gap: float = 0.01) -> list[tuple[Outcome, Outcome]]:
    """Claims with the same status and near-equal support but different dispute.

    These are the controlled comparisons: everything the formula reads is held
    fixed except the dispute mass, so any change in contribution is attributable
    to dispute alone."""
    pairs = []
    for status in STATUS_VALUE:
        group = [o for o in outcomes if o.status == status]
        group.sort(key=lambda o: o.support)
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if b.support - a.support > tol:
                    break
                if abs(b.dispute - a.dispute) < min_gap:
                    continue
                lo, hi = (a, b) if a.dispute < b.dispute else (b, a)
                pairs.append((lo, hi))
    return pairs


def bug_population(outcomes: list[Outcome]) -> list[Outcome]:
    """Claims where the bug can actually bite.

    A `disputed` claim has value 0, so its numerator contribution is 0 whatever
    the weight — inflating its weight cannot reward it. The bug only shows on a
    claim that carries dispute mass yet was NOT classified disputed, which the
    `dispute >= ratio * support` rule permits whenever support is large."""
    return [o for o in outcomes if o.status != "disputed" and o.dispute > 0]


def pair_verdict(pairs, variant: str) -> dict:
    """How often the higher-dispute claim contributes MORE (the bug)."""
    worse = better = equal = 0
    ref_worse = ref_better = ref_equal = 0
    for lo, hi in pairs:
        d = contribution(hi, variant) - contribution(lo, variant)
        if d > 1e-9:
            worse += 1
        elif d < -1e-9:
            better += 1
        else:
            equal += 1
        r = reference_score(hi, variant) - reference_score(lo, variant)
        if r > 1e-9:
            ref_worse += 1
        elif r < -1e-9:
            ref_better += 1
        else:
            ref_equal += 1
    n = len(pairs) or 1
    return {
        "pairs": len(pairs),
        "numerator_dispute_rewarded": worse,
        "numerator_dispute_penalised": better,
        "numerator_tied": equal,
        "numerator_violation_rate": worse / n,
        "refmix_dispute_rewarded": ref_worse,
        "refmix_dispute_penalised": ref_better,
        "refmix_tied": ref_equal,
        "refmix_violation_rate": ref_worse / n,
    }


# --- report -----------------------------------------------------------------


def verify_reproduction(by_hotspot, snap) -> dict:
    """Which formula, replayed from the snapshot, returns the published score?

    Nothing else in this module means anything until one of them does. Both the
    shipped and the pre-2026-08-20 formula are checked because a snapshot taken
    around a redeploy legitimately contains rows written by either — reporting
    only one would look like a broken reconstruction rather than a stale row.
    The two agree exactly on any claim with no dispute mass, so a snapshot where
    both match perfectly means no claim in it carried a contradiction."""
    result = {}
    for label, variant in (("shipped", SHIPPED_VARIANT),
                           ("pre_2026_08_20", PRE_2026_08_20_VARIANT)):
        matched = mismatched = missing = 0
        worst = 0.0
        for hid, outcomes in by_hotspot.items():
            stored = (snap["hotspots"].get(hid) or {}).get("consistency_score")
            if stored is None:
                missing += 1
                continue
            delta = abs(hotspot_score(outcomes, variant) - stored)
            worst = max(worst, delta)
            if delta < 1e-6:
                matched += 1
            else:
                mismatched += 1
        result[label] = {"variant": variant, "matched": matched,
                         "mismatched": mismatched, "no_stored_score": missing,
                         "max_abs_error": worst}
    return result


def run(snapshot: Path) -> dict:
    snap = load_snapshot(snapshot)
    by_hotspot, diagnostics = build_outcomes(snap)
    all_outcomes = [o for v in by_hotspot.values() for o in v]
    pairs = dispute_pairs(all_outcomes)
    bugged = bug_population(all_outcomes)

    hotspot_ids = sorted(by_hotspot)
    conf = {h: snap["hotspots"][h]["conf_score"] for h in hotspot_ids
            if h in snap["hotspots"] and snap["hotspots"][h]["conf_score"] is not None}

    scores: dict[str, dict[int, float]] = {}
    for name in VARIANTS:
        scores[name] = {h: hotspot_score(by_hotspot[h], name) for h in hotspot_ids}

    baseline = scores["old"]
    report: dict = {
        "snapshot": snap["meta"],
        "diagnostics": diagnostics,
        "reproduces_published_score": verify_reproduction(by_hotspot, snap),
        "claim_status_counts": {
            s: sum(1 for o in all_outcomes if o.status == s) for s in STATUS_VALUE
        },
        "claims_with_no_surviving_evidence": sum(
            1 for o in all_outcomes if o.support + o.dispute == 0.0),
        "claims_with_any_dispute": sum(1 for o in all_outcomes if o.dispute > 0),
        "bug_population": [{
            "hotspot_id": o.hotspot_id, "claim_id": o.claim_id, "status": o.status,
            "support": round(o.support, 4), "dispute": round(o.dispute, 4),
            "supporters": o.supporters, "contradictors": o.contradictors,
            "text": o.text,
            "w_times_v": {n: round(contribution(o, n), 4) for n in VARIANTS},
        } for o in bugged],
        "variants": {},
    }

    for name in VARIANTS:
        weight_fn, _value_fn = VARIANTS[name]
        vals = [scores[name][h] for h in hotspot_ids]
        pearson_ids = [h for h in hotspot_ids if h in conf]
        entry = {
            "distribution": describe(vals),
            "fr13_bucket_changes_vs_old": sum(
                1 for h in hotspot_ids
                if fr13_bucket(scores[name][h]) != fr13_bucket(baseline[h])),
            "decile_changes_vs_old": sum(
                1 for h in hotspot_ids
                if decile(scores[name][h]) != decile(baseline[h])),
            "fr13_buckets": {
                b: sum(1 for h in hotspot_ids if fr13_bucket(scores[name][h]) == b)
                for b in ("green", "yellow", "grey")
            },
            "mean_abs_delta_vs_old": (
                sum(abs(scores[name][h] - baseline[h]) for h in hotspot_ids)
                / max(len(hotspot_ids), 1)),
            "pearson_vs_conf": pearson([scores[name][h] for h in pearson_ids],
                                       [conf[h] for h in pearson_ids]),
            "spearman_vs_conf": spearman([scores[name][h] for h in pearson_ids],
                                         [conf[h] for h in pearson_ids]),
            "conf_pairs": len(pearson_ids),
            "monotonicity_real_pairs": pair_verdict(pairs, name),
            "monotonicity_real_pairs_by_status": {
                s: pair_verdict([p for p in pairs if p[0].status == s], name)
                for s in STATUS_VALUE
            },
            "monotonicity_counterfactual": counterfactual_check(all_outcomes, name),
            "monotonicity_counterfactual_bug_population":
                counterfactual_check(bugged, name),
            "dispute_sweep_corroborated": dispute_sweep(name, "corroborated"),
            "dispute_sweep_uncorroborated": dispute_sweep(name, "uncorroborated"),
            "dispute_sweep_disputed": dispute_sweep(name, "disputed"),
            # A variant that keeps a disputed claim's weight keeps its downward
            # pull; one that shrinks it silences the disagreement instead of
            # penalising it, which raises the hotspot score.
            "mean_weight_disputed_claims": (
                sum(weight_fn(o) for o in all_outcomes if o.status == "disputed")
                / max(sum(1 for o in all_outcomes if o.status == "disputed"), 1)),
            "mean_weight_all_claims": (
                sum(weight_fn(o) for o in all_outcomes) / max(len(all_outcomes), 1)),
        }
        report["variants"][name] = entry

    report["top_movers"] = _top_movers(by_hotspot, scores, baseline, snap)
    return report


def _top_movers(by_hotspot, scores, baseline, snap, limit: int = 5) -> dict:
    movers = {}
    for name in VARIANTS:
        if name == "old":
            continue
        ranked = sorted(baseline, key=lambda h: -abs(scores[name][h] - baseline[h]))
        movers[name] = [{
            "hotspot_id": h,
            "name": (snap["hotspots"].get(h) or {}).get("name"),
            "old": baseline[h],
            "new": scores[name][h],
            "delta": scores[name][h] - baseline[h],
            "claims": [{
                "text": o.text[:110],
                "status": o.status,
                "support": round(o.support, 3),
                "dispute": round(o.dispute, 3),
                "supporters": o.supporters,
                "contradictors": o.contradictors,
            } for o in by_hotspot[h]],
        } for h in ranked[:limit]]
    return movers


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest consistency_score weightings")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--out", help="write full JSON report here")
    args = parser.parse_args()
    report = run(Path(args.snapshot))
    text = json.dumps(report, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
