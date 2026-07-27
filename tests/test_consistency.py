"""Consistency engine unit tests: evidence rendering, extraction, consensus (FR-22)."""
from pipeline.consistency import render_evidence_text


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
