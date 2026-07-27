"""Consistency engine unit tests: evidence rendering, extraction, consensus (FR-22)."""
from pipeline.consistency import (
    ExtractedClaim,
    build_claims_prompt,
    extract_claims,
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
        return ('{"claims": [{"text": "Army advanced north.", "source_indices": [1, 2]}]}',
                "fake-model")
    claims = extract_claims(_EVIDENCE, llm=fake_llm)
    assert claims == [ExtractedClaim(text="Army advanced north.", source_indices=[1, 2])]


def test_extract_claims_caps_and_filters_bad_indices(monkeypatch):
    monkeypatch.setenv("SENTINEL_CONSISTENCY_MAX_CLAIMS", "2")
    def fake_llm(prompt):
        return ('{"claims": ['
                '{"text": "c1", "source_indices": [1]},'
                '{"text": "c2", "source_indices": [99]},'
                '{"text": "c3", "source_indices": [2]}]}', "fake-model")
    claims = extract_claims(_EVIDENCE, llm=fake_llm)
    assert len(claims) == 2                      # capped at MAX_CLAIMS
    assert claims[1].source_indices == []        # index 99 out of range -> dropped


def test_extract_claims_invalid_json_returns_empty():
    claims = extract_claims(_EVIDENCE, llm=lambda p: ("not json at all", "fake-model"))
    assert claims == []
