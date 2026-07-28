"""Consistency engine unit tests: evidence rendering, extraction, consensus (FR-22)."""
import numpy as np

from pipeline.consistency import (
    ClaimVerdict,
    ExtractedClaim,
    build_claims_prompt,
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
