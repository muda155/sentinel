"""Synthetic contradiction injection: the engine must flag planted disputes (FR-22 eval)."""
import os

import pytest

from eval.consistency.inject import detection_rate, inject_contradiction
from pipeline.consistency import ExtractedClaim, consensus, judge_claims


class FakeJudge:
    def classify_pairs(self, pairs):
        out = []
        for premise, hypothesis in pairs:
            if premise.startswith("CONTRARY:"):
                out.append(("contradicts", 0.95))
            else:
                out.append(("supports", 0.9))
        return out


_EVIDENCE = [
    {"event_id": 1, "citation_index": 1, "domain": "a.com", "trust_score": 1.0,
     "evidence_text": "Army advanced 5 km north."},
]


def test_inject_contradiction_appends_fresh_row():
    injected = inject_contradiction(_EVIDENCE, "Army advanced north.")
    assert len(injected) == len(_EVIDENCE) + 1
    fake = injected[-1]
    assert fake["evidence_text"].startswith("CONTRARY:")
    assert fake["citation_index"] == 2
    assert fake["domain"] not in {"a.com"}
    assert fake["event_id"] < 0  # synthetic marker, never a real event


def test_planted_contradiction_is_detected():
    claim = ExtractedClaim(text="Army advanced north.", source_indices=[])
    injected = inject_contradiction(_EVIDENCE, claim.text)
    judgments = judge_claims([claim], injected, FakeJudge())
    verdicts = consensus([claim], injected, judgments)
    assert verdicts[0].status == "disputed"


def test_detection_rate_is_fraction():
    cases = [(_EVIDENCE, "Army advanced north."), (_EVIDENCE, "Army moved north.")]
    assert detection_rate(cases, FakeJudge()) == 1.0


@pytest.mark.slow
@pytest.mark.skipif(os.getenv("SENTINEL_NLI_TEST") != "1",
                    reason="set SENTINEL_NLI_TEST=1 for the real-model injection test")
def test_planted_contradiction_detected_by_real_model():
    from pipeline.nli import NLIJudge
    claim = ExtractedClaim(text="The army advanced north.", source_indices=[])
    injected = inject_contradiction(_EVIDENCE, claim.text)
    judgments = judge_claims([claim], injected, NLIJudge())
    verdicts = consensus([claim], injected, judgments)
    assert verdicts[0].status == "disputed"
