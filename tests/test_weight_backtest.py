"""Tests for eval/consistency/weight_backtest.py.

Two things need proving. First that `reconstruct` replays
`pipeline.consistency.consensus` exactly — a backtest that disagrees with the
engine measures a formula nobody shipped. Second that each variant's
monotonicity classification is a fact about the formula and not an artifact of
whatever claims happen to be in the database today.
"""
from __future__ import annotations

import json

import pytest

from eval.consistency.weight_backtest import (
    SHIPPED_VARIANT,
    VARIANTS,
    Outcome,
    build_outcomes,
    clean_twin,
    contribution,
    counterfactual_check,
    dispute_sweep,
    hotspot_score,
    load_snapshot,
    pearson,
    reconstruct,
    reference_score,
    spearman,
)
from pipeline.consistency import ClaimVerdict, EvidenceJudgment, consensus
from pipeline.consistency import hotspot_consistency_score as engine_score


def _outcome(status="uncorroborated", support=0.0, dispute=0.0, **kw):
    return Outcome(claim_id=kw.get("claim_id", 1), hotspot_id=1, text="t",
                   status=status, support=support, dispute=dispute,
                   supporters=kw.get("supporters", 0),
                   contradictors=kw.get("contradictors", 0), stored_weight=None)


# --- fidelity to the shipped engine ----------------------------------------


class _Claim:
    def __init__(self, text, source_indices):
        self.text = text
        self.source_indices = source_indices


def test_reconstruct_matches_consensus_on_the_same_inputs():
    """Same judgments in, same support/dispute/status out as consensus()."""
    evidence = [
        {"event_id": 10, "citation_index": 1, "domain": "a.com", "trust_score": 1.0,
         "evidence_text": "x"},
        {"event_id": 11, "citation_index": 2, "domain": "b.com", "trust_score": 0.8,
         "evidence_text": "y"},
        {"event_id": 12, "citation_index": 3, "domain": "c.com", "trust_score": 0.6,
         "evidence_text": "z"},
        {"event_id": 13, "citation_index": 4, "domain": "d.com", "trust_score": 0.4,
         "evidence_text": "w"},
    ]
    row = [
        # a.com is the claim's own source: supports, but must not corroborate.
        EvidenceJudgment(10, 1, "a.com", "supports", 0.99),
        EvidenceJudgment(11, 2, "b.com", "supports", 0.90),
        EvidenceJudgment(12, 3, "c.com", "supports", 0.70),
        EvidenceJudgment(13, 4, "d.com", "contradicts", 0.80),
    ]
    engine = consensus([_Claim("c", [1])], evidence, [row])[0]

    claim = {"claim_id": 1, "hotspot_id": 1, "claim_text": "c",
             "status": engine.status, "consensus_weight": engine.weight,
             "origin_domains": ["a.com"]}
    snapshot_evidence = [{"claim_id": 1, "event_id": j.event_id,
                          "relation": j.relation, "probability": j.probability}
                         for j in row]
    event_domain = {e["event_id"]: {"domain": e["domain"],
                                    "trust_score": e["trust_score"]}
                    for e in evidence}

    got = reconstruct(claim, snapshot_evidence, event_domain)
    assert got.status == engine.status
    assert got.support == pytest.approx(engine.support)
    assert got.dispute == pytest.approx(engine.dispute)


def test_shipped_variant_reproduces_engine_hotspot_score():
    """UPDATED 2026-08-20: this used to assert the `old` variant matched the
    engine. It no longer can — the engine now scales value by the agreement
    ratio, which is exactly variant C_capped_k1. `old` is retained in the
    harness only to identify scores written before the change."""
    verdicts = [
        ClaimVerdict("a", "corroborated", 3.0, 0.0, max(3.0, 0.1)),
        ClaimVerdict("b", "disputed", 0.5, 1.5, max(2.0, 0.1)),
        ClaimVerdict("c", "uncorroborated", 0.0, 0.0, 0.1),
        ClaimVerdict("d", "corroborated", 2.0, 0.5, max(2.5, 0.1)),
    ]
    outcomes = [_outcome("corroborated", 3.0, 0.0), _outcome("disputed", 0.5, 1.5),
                _outcome("uncorroborated", 0.0, 0.0),
                _outcome("corroborated", 2.0, 0.5)]
    assert hotspot_score(outcomes, SHIPPED_VARIANT) == pytest.approx(engine_score(verdicts))
    # and the harness's historical baseline must now DIFFER, or it is not
    # measuring the change it exists to measure
    assert hotspot_score(outcomes, "old") != pytest.approx(engine_score(verdicts))


def test_reconstruct_reduces_per_domain_not_per_event():
    """Two events from one outlet are one vote, and the strongest one wins."""
    claim = {"claim_id": 1, "hotspot_id": 1, "claim_text": "c", "status": "x",
             "consensus_weight": None, "origin_domains": []}
    evidence = [
        {"claim_id": 1, "event_id": 1, "relation": "supports", "probability": 0.7},
        {"claim_id": 1, "event_id": 2, "relation": "supports", "probability": 0.9},
    ]
    event_domain = {1: {"domain": "same.com", "trust_score": 1.0},
                    2: {"domain": "same.com", "trust_score": 1.0}}
    got = reconstruct(claim, evidence, event_domain)
    assert got.supporters == 1
    assert got.support == pytest.approx(0.9)


def test_reconstruct_ignores_neutral_and_below_threshold_pairs():
    claim = {"claim_id": 1, "hotspot_id": 1, "claim_text": "c", "status": "x",
             "consensus_weight": None, "origin_domains": []}
    evidence = [
        {"claim_id": 1, "event_id": 1, "relation": "neutral", "probability": 0.99},
        {"claim_id": 1, "event_id": 2, "relation": "supports", "probability": 0.59},
    ]
    event_domain = {1: {"domain": "a.com", "trust_score": 1.0},
                    2: {"domain": "b.com", "trust_score": 1.0}}
    got = reconstruct(claim, evidence, event_domain)
    assert (got.support, got.dispute, got.status) == (0.0, 0.0, "uncorroborated")


def test_null_origin_domains_taints_the_whole_hotspot(tmp_path):
    """Migration 023: NULL means unverifiable, never 'no origin domains'."""
    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "claims.jsonl").write_text(
        json.dumps({"claim_id": 1, "hotspot_id": 7, "claim_text": "a",
                    "status": "uncorroborated", "consensus_weight": 0.1,
                    "origin_domains": None}) + "\n"
        + json.dumps({"claim_id": 2, "hotspot_id": 7, "claim_text": "b",
                      "status": "uncorroborated", "consensus_weight": 0.1,
                      "origin_domains": ["a.com"]}) + "\n"
        + json.dumps({"claim_id": 3, "hotspot_id": 8, "claim_text": "c",
                      "status": "uncorroborated", "consensus_weight": 0.1,
                      "origin_domains": ["a.com"]}) + "\n", encoding="utf-8")
    (snap / "claim_evidence.jsonl").write_text("", encoding="utf-8")
    (snap / "event_domain.jsonl").write_text("", encoding="utf-8")
    (snap / "hotspots.jsonl").write_text(
        json.dumps({"hotspot_id": 7, "consistency_score": 50.0, "conf_score": 1.0})
        + "\n" + json.dumps({"hotspot_id": 8, "consistency_score": 50.0,
                             "conf_score": 1.0}) + "\n", encoding="utf-8")
    (snap / "meta.json").write_text("{}", encoding="utf-8")

    by_hotspot, diagnostics = build_outcomes(load_snapshot(snap))
    assert 7 not in by_hotspot, "a hotspot with an unverifiable claim must be dropped whole"
    assert 8 in by_hotspot
    assert diagnostics["claims_unverifiable_null_origin"] == 1
    assert diagnostics["hotspots_dropped_tainted"] == 1


# --- the property the project owner asked for -------------------------------

# Each variant's admissibility is a theorem, not a measurement: with
# w'(d) <= 0 and v'(d) <= 0 the hotspot score is non-increasing in dispute for
# EVERY possible set of sibling claims. Encoding it here keeps the comparison
# table honest if someone edits a variant.
MONOTONE_VARIANTS = ["A_support_weight", "B_agreement_value", "C_capped_k1"]
NON_MONOTONE_VARIANTS = ["old", "C_capped_k0.5", "D_weight_minus"]


@pytest.mark.parametrize("variant", MONOTONE_VARIANTS)
@pytest.mark.parametrize("status", ["corroborated", "uncorroborated", "disputed"])
def test_admissible_variants_never_reward_dispute(variant, status):
    rows = dispute_sweep(variant, status)
    scores = [r["refmix_score"] for r in rows]
    numerators = [r["w_times_v"] for r in rows]
    assert scores == sorted(scores, reverse=True), f"{variant}/{status} score rose with dispute"
    assert numerators == sorted(numerators, reverse=True)


def test_old_formula_rewards_dispute_on_a_corroborated_claim():
    """The reported bug, as an executable statement."""
    rows = dispute_sweep("old", "corroborated")
    assert rows[0]["w_times_v"] == pytest.approx(2.0)
    assert rows[-1]["w_times_v"] == pytest.approx(6.0)
    assert rows[-1]["refmix_score"] > rows[0]["refmix_score"]


def test_partial_penalty_still_rewards_dispute_in_the_numerator():
    """C with k < 1 leaves w*v = V*(support + (1-k)*dispute), still rising."""
    rows = dispute_sweep("C_capped_k0.5", "corroborated")
    assert rows[-1]["w_times_v"] > rows[0]["w_times_v"]


def test_weight_penalty_inverts_on_disputed_claims():
    """D shrinks a disputed claim's weight, and a value-0 claim with less
    weight pulls the hotspot score UP. Penalising the weight of the claims the
    engine most wants to punish is backwards."""
    rows = dispute_sweep("D_weight_minus", "disputed")
    assert rows[-1]["refmix_score"] > rows[0]["refmix_score"]


def test_agreement_value_discards_the_two_domain_corroboration_gate():
    """B reads only the support/dispute ratio, so one uncontested single-source
    claim scores a perfect 100 — the >=2 distinct domains rule stops mattering."""
    single_source = _outcome("uncorroborated", support=0.36, supporters=1)
    assert hotspot_score([single_source], "B_agreement_value") == pytest.approx(100.0)
    assert hotspot_score([single_source], "C_capped_k1") == pytest.approx(50.0)


def test_zero_evidence_claim_keeps_the_uncorroborated_value_everywhere():
    """support == dispute == 0 is the modal claim in live data; 0/0 must not
    become 0 (an accusation) or 1 (an unearned corroboration)."""
    empty = _outcome("uncorroborated", 0.0, 0.0)
    for variant in VARIANTS:
        assert hotspot_score([empty], variant) == pytest.approx(50.0), variant


def test_clean_twin_changes_only_dispute():
    o = _outcome("corroborated", 2.0, 0.5, supporters=4, contradictors=1)
    twin = clean_twin(o)
    assert (twin.support, twin.status, twin.supporters) == (o.support, o.status, o.supporters)
    assert twin.dispute == 0.0


def test_counterfactual_check_flags_the_old_formula():
    bugged = _outcome("corroborated", 2.0, 0.5, supporters=4, contradictors=1)
    old = counterfactual_check([bugged], "old")
    assert old["numerator_dispute_rewarded"] == 1
    fixed = counterfactual_check([bugged], "C_capped_k1")
    assert fixed["numerator_dispute_rewarded"] == 0
    assert fixed["refmix_dispute_penalised"] == 1


def test_reference_score_reacts_to_weight_as_well_as_value():
    """w*v alone hides variants that shrink numerator and denominator together."""
    heavy = _outcome("disputed", 0.0, 4.0)
    light = _outcome("disputed", 0.0, 0.2)
    assert contribution(heavy, "old") == contribution(light, "old") == 0.0
    assert reference_score(heavy, "old") < reference_score(light, "old")


# --- statistics -------------------------------------------------------------


def test_pearson_and_spearman_against_known_values():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert pearson(xs, [2.0, 4.0, 6.0, 8.0, 10.0]) == pytest.approx(1.0)
    assert pearson(xs, [5.0, 4.0, 3.0, 2.0, 1.0]) == pytest.approx(-1.0)
    # monotone but curved: Spearman sees a perfect rank match, Pearson does not
    ys = [1.0, 4.0, 9.0, 16.0, 25.0]
    assert spearman(xs, ys) == pytest.approx(1.0)
    assert pearson(xs, ys) < 1.0


def test_spearman_averages_tied_ranks():
    assert spearman([1.0, 1.0, 2.0], [1.0, 1.0, 2.0]) == pytest.approx(1.0)


def test_correlations_are_none_on_a_constant_series():
    assert pearson([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None
