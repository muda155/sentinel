"""Consistency engine unit tests: evidence rendering, extraction, consensus (FR-22)."""
import numpy as np
import pytest

from pipeline.consistency import (
    ClaimVerdict,
    ExtractedClaim,
    build_claims_prompt,
    claim_value,
    consensus,
    extract_claims,
    hotspot_consistency_score,
    judge_claims,
    render_evidence_text,
)


def test_render_evidence_acled_prefers_notes():
    row = {"source_system": "ACLED", "title": "armed_conflict: Test City",
           "notes": "Clashes reported near Test City.", "fatalities": 3}
    text = render_evidence_text(row)
    assert text == "Clashes reported near Test City. Fatalities: 3."


def test_render_evidence_acled_falls_back_to_title():
    row = {"source_system": "ACLED", "title": "armed_conflict: Test City", "notes": None}
    assert render_evidence_text(row) == "armed_conflict: Test City"


def test_render_evidence_gdelt_structured_sentence():
    row = {"source_system": "GDELT", "title": "MILITARY", "actor1_name": "MILITARY",
           "actor2_name": "REBELS", "goldstein_scale": -8.0, "avg_tone": -5.2,
           "num_sources": 12}
    text = render_evidence_text(row)
    assert text == ("MILITARY. Reported: MILITARY vs REBELS; "
                    "Goldstein -8; tone -5.2; 12 reports.")


def test_render_evidence_gdelt_omits_null_fields():
    row = {"source_system": "GDELT", "title": "MILITARY", "actor1_name": "MILITARY",
           "actor2_name": None, "goldstein_scale": None, "avg_tone": None,
           "num_sources": None}
    assert render_evidence_text(row) == "MILITARY. Reported: MILITARY."


_EVIDENCE = [
    {"event_id": 1, "citation_index": 1, "domain": "a.com", "trust_score": 1.0,
     "evidence_text": "Army advanced 5 km north."},
    {"event_id": 2, "citation_index": 2, "domain": "b.com", "trust_score": 0.8,
     "evidence_text": "Army moved north of the city."},
]


def test_build_claims_prompt_numbers_evidence():
    prompt = build_claims_prompt(_EVIDENCE)
    assert "[1] Army advanced 5 km north." in prompt
    assert "[2] Army moved north of the city." in prompt
    assert "JSON" in prompt


def test_extract_claims_parses_and_validates():
    def fake_llm(prompt):
        return ('{"claims": [{"text": "The army advanced north.", "source_indices": [1, 2]}]}',
                "fake-model")
    claims = extract_claims(_EVIDENCE, llm=fake_llm)
    assert claims == [ExtractedClaim(text="The army advanced north.", source_indices=[1, 2])]


def test_extract_claims_caps_and_filters_bad_indices(monkeypatch):
    monkeypatch.setenv("SENTINEL_CONSISTENCY_MAX_CLAIMS", "2")
    def fake_llm(prompt):
        return ('{"claims": ['
                '{"text": "The first clash was reported.", "source_indices": [1]},'
                '{"text": "The second clash was reported.", "source_indices": [99]},'
                '{"text": "The third clash was reported.", "source_indices": [2]}]}',
                "fake-model")
    claims = extract_claims(_EVIDENCE, llm=fake_llm)
    assert len(claims) == 2                      # capped at MAX_CLAIMS
    assert claims[1].source_indices == []        # index 99 out of range -> dropped


def test_extract_claims_invalid_json_returns_empty():
    claims = extract_claims(_EVIDENCE, llm=lambda p: ("not json at all", "fake-model"))
    assert claims == []


class FakeJudge:
    """Deterministic NLI stand-in: keyword-driven relations."""
    def classify_pairs(self, pairs):
        out = []
        for premise, _hypothesis in pairs:
            if "retreated" in premise:
                out.append(("contradicts", 0.95))
            elif "advanced" in premise or "moved" in premise:
                out.append(("supports", 0.9))
            else:
                out.append(("neutral", 0.8))
        return out


_EV3 = [
    {"event_id": 1, "citation_index": 1, "domain": "a.com", "trust_score": 1.0,
     "evidence_text": "Army advanced 5 km north."},
    {"event_id": 2, "citation_index": 2, "domain": "b.com", "trust_score": 0.8,
     "evidence_text": "Army moved north of the city."},
    {"event_id": 3, "citation_index": 3, "domain": "c.com", "trust_score": 0.6,
     "evidence_text": "Army retreated south."},
]


def _claims():
    return [ExtractedClaim(text="Army advanced north.", source_indices=[1])]


def test_judge_claims_shape():
    judgments = judge_claims(_claims(), _EV3, FakeJudge())
    assert len(judgments) == 1 and len(judgments[0]) == 3
    assert judgments[0][0].relation == "supports"
    assert judgments[0][2].relation == "contradicts"


def test_consensus_corroborated_needs_two_nonorigin_domains():
    ev = _EV3[:2]  # a.com (origin) + b.com supporting
    judgments = judge_claims(_claims(), ev, FakeJudge())
    verdicts = consensus(_claims(), ev, judgments)
    # Only b.com is non-origin support -> NOT corroborated
    assert verdicts[0].status == "uncorroborated"


def test_consensus_disputed_when_contradiction_outweighs():
    judgments = judge_claims(_claims(), _EV3, FakeJudge())
    verdicts = consensus(_claims(), _EV3, judgments)
    # support (non-origin b.com: 0.8*0.9=0.72), dispute (c.com: 0.6*0.95=0.57)
    # dispute >= 0.5 * support -> disputed
    assert verdicts[0].status == "disputed"
    assert verdicts[0].support > 0 and verdicts[0].dispute > 0


def test_consensus_low_probability_pairs_are_ignored(monkeypatch):
    monkeypatch.setenv("SENTINEL_NLI_MIN_PROB", "0.99")
    judgments = judge_claims(_claims(), _EV3, FakeJudge())
    verdicts = consensus(_claims(), _EV3, judgments)
    assert verdicts[0].status == "uncorroborated"  # nothing clears 0.99


def test_score_formula():
    verdicts = [
        ClaimVerdict(text="a", status="corroborated", support=1.5, dispute=0.0,
                     weight=1.5, evidence=[]),
        ClaimVerdict(text="b", status="disputed", support=0.7, dispute=0.6,
                     weight=1.3, evidence=[]),
    ]
    # 100 * (1.5*1.0 + 1.3*0.0) / (1.5+1.3) = 53.57...
    assert abs(hotspot_consistency_score(verdicts) - 53.571) < 0.01
    assert hotspot_consistency_score([]) is None


def test_score_all_uncorroborated_is_50():
    verdicts = [ClaimVerdict(text="a", status="uncorroborated", support=0.0,
                             dispute=0.0, weight=0.1, evidence=[])]
    assert hotspot_consistency_score(verdicts) == 50.0


# --- FR-22(d) agreement-scaled claim value (changed 2026-08-20) -------------
#
# v_c = V[status] * support/(support+dispute). Weight stays support+dispute.
# The defect this replaced: a dispute vote raised only the WEIGHT, so a claim
# carrying a contradiction contributed more to the score than a clean claim of
# equal support whenever the contradiction failed to flip the status.


def _v(status, support, dispute):
    return ClaimVerdict(text="c", status=status, support=support, dispute=dispute,
                        weight=max(support + dispute, 0.1), evidence=[])


@pytest.mark.parametrize("status,expected", [
    ("corroborated", 1.0), ("uncorroborated", 0.5), ("disputed", 0.0),
])
def test_clean_claim_value_is_unchanged_from_the_status_constant(status, expected):
    """THE load-bearing invariant: with dispute == 0 the agreement ratio is 1,
    so every claim that carries no contradiction scores exactly what it scored
    before. This is why the change does not move the reported figures."""
    assert claim_value(_v(status, support=3.0, dispute=0.0)) == pytest.approx(expected)


@pytest.mark.parametrize("status", ["corroborated", "uncorroborated", "disputed"])
@pytest.mark.parametrize("support", [0.4, 1.0, 3.7, 12.0])
def test_clean_claims_score_identically_under_old_and_new_formulas(status, support):
    verdicts = [_v(status, support, 0.0), _v("uncorroborated", 0.0, 0.0)]
    legacy_value = {"corroborated": 1.0, "uncorroborated": 0.5, "disputed": 0.0}
    total = sum(v.weight for v in verdicts)
    legacy = 100.0 * sum(v.weight * legacy_value[v.status] for v in verdicts) / total
    assert hotspot_consistency_score(verdicts) == pytest.approx(legacy)


def test_zero_evidence_claim_keeps_its_status_value():
    """support == dispute == 0 must not divide by zero and must not be read as
    total disagreement. 448 of 597 claims on the 2026-08-20 snapshot are here."""
    assert claim_value(_v("uncorroborated", 0.0, 0.0)) == pytest.approx(0.5)
    assert claim_value(_v("corroborated", 0.0, 0.0)) == pytest.approx(1.0)
    assert claim_value(_v("disputed", 0.0, 0.0)) == pytest.approx(0.0)


@pytest.mark.parametrize("status", ["corroborated", "uncorroborated", "disputed"])
def test_claim_value_never_rises_with_dispute(status):
    values = [claim_value(_v(status, support=2.0, dispute=d))
              for d in (0.0, 0.1, 0.5, 1.0, 2.0, 5.0, 50.0)]
    assert values == sorted(values, reverse=True)
    assert all(0.0 <= v <= 1.0 for v in values)


# The admissibility criterion is w'(d) <= 0 AND v'(d) <= 0, which makes the
# hotspot score non-increasing in dispute for EVERY sibling set. Testing one
# sibling configuration would not distinguish that from a formula that merely
# happens to work against the siblings chosen.
@pytest.mark.parametrize("siblings", [
    [],
    [_v("corroborated", 5.0, 0.0)],
    [_v("disputed", 0.0, 4.0)],
    [_v("uncorroborated", 0.0, 0.0)],
    [_v("uncorroborated", 0.0, 0.0)] * 7,
    [_v("corroborated", 9.0, 0.0), _v("disputed", 0.1, 3.0),
     _v("uncorroborated", 0.6, 0.0)],
    [_v("corroborated", 0.4, 0.0)] * 3 + [_v("disputed", 0.0, 0.4)] * 2,
], ids=["alone", "strong-clean", "heavily-disputed", "empty", "many-empty",
        "mixed", "many-small"])
@pytest.mark.parametrize("status", ["corroborated", "uncorroborated", "disputed"])
def test_hotspot_score_never_rises_when_one_claim_gains_dispute(siblings, status):
    scores = [
        hotspot_consistency_score([_v(status, support=2.0, dispute=d), *siblings])
        for d in (0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 16.0)
    ]
    assert scores == sorted(scores, reverse=True), (
        f"{status} with siblings {siblings!r} produced a rising score: {scores}")


def test_contested_claim_now_contributes_less_than_a_clean_twin():
    """The exact defect, as a regression test. Two corroborated claims of equal
    support; only one carries a contradiction. It must not score higher."""
    clean = [_v("corroborated", 3.0, 0.0), _v("uncorroborated", 0.0, 0.0)]
    contested = [_v("corroborated", 3.0, 1.0), _v("uncorroborated", 0.0, 0.0)]
    assert hotspot_consistency_score(contested) < hotspot_consistency_score(clean)


def test_dispute_does_not_inflate_the_weight_side_of_the_ratio():
    """`weight` deliberately still includes dispute — total evidence mass is
    how confident the verdict is. Only `value` was changed. Guards against a
    future 'fix' that also drops dispute from the weight, which would MUTE a
    disputed claim (weight -> support) instead of penalising it."""
    verdict = _v("disputed", support=0.0, dispute=4.0)
    assert verdict.weight == pytest.approx(4.0)
    loud = hotspot_consistency_score([verdict, _v("corroborated", 3.0, 0.0)])
    muted = hotspot_consistency_score([_v("disputed", 0.0, 0.1),
                                       _v("corroborated", 3.0, 0.0)])
    assert loud < muted


def test_score_stays_within_bounds_on_extreme_dispute():
    for d in (0.0, 1e-9, 7.0, 1e6):
        score = hotspot_consistency_score([_v("corroborated", 1.0, d)])
        assert 0.0 <= score <= 100.0


def test_extract_claims_drops_bare_entity_fragments():
    def fake_llm(prompt):
        return ('{"claims": ['
                '{"text": "WASHINGTON", "source_indices": [1]},'
                '{"text": "A US vs IRAN", "source_indices": [1]},'
                '{"text": "RUSSIAN vs IRANIAN", "source_indices": [2]},'
                '{"text": "Army advanced north of the city.", "source_indices": [1, 2]}]}',
                "fake-model")
    claims = extract_claims(_EVIDENCE, llm=fake_llm)
    assert [c.text for c in claims] == ["Army advanced north of the city."]


def test_extract_claims_all_fragments_returns_empty():
    # Degenerate extraction must yield NO claims -> engine skips -> score NULL,
    # instead of judging noise into an all-disputed score of 0.
    def fake_llm(prompt):
        return ('{"claims": [{"text": "FIGHTER", "source_indices": [1]},'
                '{"text": "THE INTERNATIONAL COMMUNITY", "source_indices": [2]}]}',
                "fake-model")
    assert extract_claims(_EVIDENCE, llm=fake_llm) == []


def test_build_claims_prompt_demands_full_sentences():
    prompt = build_claims_prompt(_EVIDENCE)
    assert "complete English sentence" in prompt
    assert "Ignore numeric metadata" in prompt
    assert '{"claims": []}' in prompt


def test_dedupe_claims_collapses_identical_text_and_merges_indices():
    from pipeline.consistency import dedupe_claims

    claims = [
        ExtractedClaim(text="Russia is mentioned", source_indices=[1]),
        ExtractedClaim(text="Russia is mentioned", source_indices=[2]),
        ExtractedClaim(text="Russia is mentioned", source_indices=[1, 3]),
    ]
    result = dedupe_claims(claims)
    assert len(result) == 1
    assert result[0].text == "Russia is mentioned"
    assert result[0].source_indices == [1, 2, 3]


def test_dedupe_claims_normalises_case_whitespace_and_trailing_period():
    from pipeline.consistency import dedupe_claims

    claims = [
        ExtractedClaim(text="The army advanced north.", source_indices=[1]),
        ExtractedClaim(text="the  army   advanced north", source_indices=[2]),
    ]
    result = dedupe_claims(claims)
    assert len(result) == 1
    assert result[0].text == "The army advanced north."   # first spelling wins
    assert result[0].source_indices == [1, 2]


def test_dedupe_claims_keeps_distinct_claims_and_order():
    from pipeline.consistency import dedupe_claims

    claims = [
        ExtractedClaim(text="The army advanced north.", source_indices=[1]),
        ExtractedClaim(text="The army retreated south.", source_indices=[2]),
    ]
    result = dedupe_claims(claims)
    assert [c.text for c in result] == [
        "The army advanced north.", "The army retreated south."
    ]


def test_dedupe_claims_empty_list():
    from pipeline.consistency import dedupe_claims

    assert dedupe_claims([]) == []


class RecordingJudge:
    """Wraps FakeJudge and records exactly which pairs it was asked about."""
    def __init__(self):
        self.seen = []
        self._inner = FakeJudge()

    def classify_pairs(self, pairs):
        self.seen.extend(pairs)
        return self._inner.classify_pairs(pairs)


def test_judge_claims_without_sim_judges_every_pair():
    from pipeline.consistency import judge_claims

    judge = RecordingJudge()
    judgments = judge_claims(_claims(), _EV3, judge)
    assert len(judge.seen) == 3            # 1 claim x 3 evidence
    assert len(judgments[0]) == 3


def test_judge_claims_gates_low_similarity_pairs_out():
    from pipeline.consistency import judge_claims

    judge = RecordingJudge()
    sim = np.array([[0.9, 0.1, 0.8]])      # middle row is off-topic
    judgments = judge_claims(_claims(), _EV3, judge, sim=sim, threshold=0.35)
    assert len(judge.seen) == 2            # the 0.1 pair never reached the model
    assert len(judgments[0]) == 3          # but the grid is still complete
    assert judgments[0][1].relation == "neutral"
    assert judgments[0][1].probability == 0.0
    assert judgments[0][1].citation_index == 2
    assert judgments[0][1].domain == "b.com"


def test_judge_claims_gate_suppresses_a_would_be_contradiction():
    # This is the M8 bug in miniature: c.com contradicts, but it is off-topic,
    # so it must never be judged and must not become a dispute.
    from pipeline.consistency import consensus, judge_claims

    sim = np.array([[0.9, 0.8, 0.05]])
    judgments = judge_claims(_claims(), _EV3, FakeJudge(), sim=sim, threshold=0.35)
    verdicts = consensus(_claims(), _EV3, judgments)
    assert verdicts[0].status != "disputed"
    assert verdicts[0].dispute == 0


def test_judge_claims_all_pairs_gated_yields_all_neutral():
    from pipeline.consistency import judge_claims

    judge = RecordingJudge()
    sim = np.array([[0.0, 0.0, 0.0]])
    judgments = judge_claims(_claims(), _EV3, judge, sim=sim, threshold=0.35)
    assert judge.seen == []
    assert all(j.relation == "neutral" for j in judgments[0])


def test_count_gated_pairs():
    from pipeline.consistency import count_gated_pairs

    sim = np.array([[0.9, 0.1, 0.8], [0.2, 0.2, 0.95]])
    assert count_gated_pairs(sim, 0.35) == 3
    assert count_gated_pairs(None, 0.35) == 0


def _c(text):
    return ExtractedClaim(text=text, source_indices=[1])


def test_vacuity_drops_claim_that_matches_everything_in_a_diverse_hotspot():
    from pipeline.consistency import filter_vacuous_claims

    claims = [_c("Russia is mentioned"), _c("The army advanced north.")]
    sim = np.array([
        [0.60, 0.61, 0.59, 0.60],   # matches everything, peaks on nothing
        [0.90, 0.85, 0.20, 0.15],   # peaks on the first two rows
    ])
    kept, kept_sim, dropped = filter_vacuous_claims(claims, sim, homogeneity=0.3)
    assert [c.text for c in kept] == ["The army advanced north."]
    assert dropped == 1
    assert kept_sim.shape == (1, 4)
    assert kept_sim[0][0] == pytest.approx(0.90)


def test_vacuity_guard_keeps_flat_claim_in_a_homogeneous_hotspot():
    # All evidence is one event, so a good claim is uniformly similar too.
    # Dropping it would discard the textbook corroboration case.
    from pipeline.consistency import filter_vacuous_claims

    claims = [_c("The army advanced north.")]
    sim = np.array([[0.80, 0.81, 0.79, 0.80]])
    kept, kept_sim, dropped = filter_vacuous_claims(claims, sim, homogeneity=0.9)
    assert len(kept) == 1
    assert dropped == 0
    assert kept_sim.shape == (1, 4)


def test_vacuity_can_drop_every_claim():
    from pipeline.consistency import filter_vacuous_claims

    claims = [_c("Russia is mentioned"), _c("Iran is mentioned")]
    sim = np.array([[0.6, 0.6, 0.6], [0.5, 0.5, 0.5]])
    kept, kept_sim, dropped = filter_vacuous_claims(claims, sim, homogeneity=0.2)
    assert kept == []
    assert dropped == 2
    assert kept_sim.shape == (0, 3)


def test_vacuity_no_claims_is_a_noop():
    from pipeline.consistency import filter_vacuous_claims

    kept, kept_sim, dropped = filter_vacuous_claims([], np.zeros((0, 3)), homogeneity=0.2)
    assert kept == [] and dropped == 0 and kept_sim.shape == (0, 3)


def _verdict(status, support, dispute):
    """A verdict with the weight consensus() would have assigned it."""
    return ClaimVerdict(text="c", status=status, support=support, dispute=dispute,
                        weight=max(support + dispute, 0.1), evidence=[])


def test_a_claim_with_no_dispute_scores_at_its_status_ceiling():
    """The invariant that keeps the agreement discount from moving clean data.

    Every corroborated/uncorroborated claim nobody contradicted must land on
    exactly 100/50 -- support/(support+dispute) is 1 when dispute is 0, so the
    discount is inert on the overwhelming majority of the corpus."""
    assert hotspot_consistency_score([_verdict("corroborated", 3.0, 0.0)]) == 100.0
    assert hotspot_consistency_score([_verdict("uncorroborated", 2.0, 0.0)]) == 50.0
    assert hotspot_consistency_score([_verdict("disputed", 0.0, 1.4)]) == 0.0


def test_dispute_lowers_a_claims_contribution_rather_than_raising_it():
    """The defect this formula replaced, stated as an assertion.

    Two corroborated claims with equal support: the one carrying contradictions
    must score lower. Under `weight = support + dispute` with a flat status
    value it scored HIGHER, because the dispute mass entered the numerator."""
    clean = hotspot_consistency_score([_verdict("corroborated", 4.0, 0.0)])
    contested = hotspot_consistency_score([_verdict("corroborated", 4.0, 1.0)])
    assert contested < clean
    assert contested == pytest.approx(80.0)  # 100 * (5 * 1.0 * 4/5) / 5


@pytest.mark.parametrize("sibling", [
    _verdict("corroborated", 5.0, 0.0),   # sibling above the claim
    _verdict("uncorroborated", 0.0, 0.0),  # sibling at the midpoint
    _verdict("disputed", 0.0, 3.0),        # sibling below the claim
    None,                                  # claim alone
])
def test_score_never_rises_as_dispute_grows(sibling):
    """Monotonicity has to hold for EVERY sibling set, not just a lucky one.

    A claim's contribution is (M + w*v)/(W + w), so whether extra mass pulls the
    score up or down depends on the siblings it is averaged against. The
    admissibility criterion (w' <= 0 and v' <= 0) is what makes the direction
    independent of them, and this sweeps the sibling term to prove it."""
    scores = []
    for dispute in (0.0, 0.5, 1.0, 2.0, 4.0, 8.0):
        verdicts = [_verdict("corroborated", 4.0, dispute)]
        if sibling is not None:
            verdicts.append(sibling)
        scores.append(hotspot_consistency_score(verdicts))
    assert scores == sorted(scores, reverse=True)
    assert scores[-1] < scores[0]


def test_a_claim_with_no_usable_evidence_keeps_its_status_value():
    """support == dispute == 0 is the modal claim, not an edge case.

    Every NLI pair gated by FR-26 or below SENTINEL_NLI_MIN_PROB leaves both
    sums at zero. There is no agreement ratio to compute, so the status value
    stands: reading 0/0 as 0 would mark three quarters of the corpus
    contradicted, reading it as 1 would corroborate it for free."""
    assert hotspot_consistency_score([_verdict("uncorroborated", 0.0, 0.0)]) == 50.0
    assert hotspot_consistency_score([_verdict("corroborated", 0.0, 0.0)]) == 100.0
