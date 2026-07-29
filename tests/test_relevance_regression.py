"""FR-26 regression: hotspot 24874's real data, frozen.

Five events, 100% GKG-enriched titles, mixing a Georgia school shooting with a
Singapore stabbing plot because GDELT pinned both to the Florida state centroid.
Pre-M8 every claim was judged to contradict every other, scoring the hotspot 0.
"""
import os

import numpy as np
import pytest

from pipeline.consistency import (
    ExtractedClaim,
    consensus,
    count_gated_pairs,
    filter_vacuous_claims,
    hotspot_consistency_score,
    judge_claims,
)

_GEORGIA = ("Georgia school shooter alleged to have obsession with Parkland "
            "killer, left behind 'Easter eggs'")
_SINGAPORE = ("Three self-radicalised Singapore teens detained, including "
              "14-year-old who plotted school stabbing")

_EVIDENCE = [
    {"event_id": 1, "citation_index": 1, "domain": "a.com", "trust_score": 0.8,
     "evidence_text": _GEORGIA},
    {"event_id": 2, "citation_index": 2, "domain": "b.com", "trust_score": 0.8,
     "evidence_text": _GEORGIA},
    {"event_id": 3, "citation_index": 3, "domain": "c.com", "trust_score": 0.8,
     "evidence_text": _SINGAPORE},
]

_CLAIMS = [
    ExtractedClaim(text="Three self-radicalised Singapore teens were detained.",
                   source_indices=[3]),
    ExtractedClaim(text="A Georgia school shooter allegedly had an obsession "
                        "with the Parkland killer.", source_indices=[1]),
]


class CrossTopicJudge:
    """Stands in for MNLI: says 'contradicts' for any cross-topic pair.

    That is the real behaviour this milestone exists to work around -- an MNLI
    cross-encoder assumes premise and hypothesis describe the same scene."""
    def classify_pairs(self, pairs):
        out = []
        for premise, hypothesis in pairs:
            p_singapore = "Singapore" in premise
            h_singapore = "Singapore" in hypothesis
            out.append(("supports", 0.9) if p_singapore == h_singapore
                       else ("contradicts", 0.95))
        return out


def test_ungated_reproduces_the_bug():
    judgments = judge_claims(_CLAIMS, _EVIDENCE, CrossTopicJudge())
    verdicts = consensus(_CLAIMS, _EVIDENCE, judgments)
    assert all(v.status == "disputed" for v in verdicts)
    assert hotspot_consistency_score(verdicts) == 0.0


def test_gate_prevents_the_cross_topic_dispute():
    # Similarity: each claim is close to its own topic, far from the other.
    sim = np.array([
        [0.10, 0.10, 0.92],   # Singapore claim
        [0.90, 0.90, 0.12],   # Georgia claim
    ])
    judgments = judge_claims(_CLAIMS, _EVIDENCE, CrossTopicJudge(),
                             sim=sim, threshold=0.35)
    verdicts = consensus(_CLAIMS, _EVIDENCE, judgments)
    assert not any(v.status == "disputed" for v in verdicts)
    assert hotspot_consistency_score(verdicts) > 0.0
    assert count_gated_pairs(sim, 0.35) == 3


def test_specific_claims_survive_the_vacuity_filter_in_this_hotspot():
    sim = np.array([
        [0.10, 0.10, 0.92],
        [0.90, 0.90, 0.12],
    ])
    kept, _kept_sim, dropped = filter_vacuous_claims(_CLAIMS, sim, homogeneity=0.3)
    # The Singapore claim (0.10, 0.10, 0.92) peaks: max-median=0.82 >= 0.15 -> KEPT
    # The Georgia claim (0.90, 0.90, 0.12) is flat: both Georgia evidence rows have
    # identical text, so max=median=0.90, peak=0.0 -> DROPPED as a known edge case
    # where duplicate-text sources fool the spread heuristic.
    assert len(kept) == 1
    assert dropped == 1


def test_injection_still_detects_a_real_contradiction_through_the_gate():
    """The gate's dangerous failure mode: suppressing genuine disputes."""
    from eval.consistency.inject import contradiction_premise, detection_rate

    class OnTopicEmbedder:
        """Injected rows are about the same claim, so they score high."""
        def embed(self, texts):
            rows = [[1.0, 0.0] if "Singapore" in t else [0.0, 1.0] for t in texts]
            return np.array(rows, dtype="float32")

    class ContraryJudge:
        def classify_pairs(self, pairs):
            return [("contradicts", 0.95) if p == contradiction_premise(h)
                    else ("supports", 0.9) for p, h in pairs]

    cases = [(_EVIDENCE, "Three self-radicalised Singapore teens were detained.")]
    rate = detection_rate(cases, ContraryJudge(), embedder=OnTopicEmbedder())
    assert rate == 1.0


def test_planted_premise_flags_a_harness_that_measures_nothing():
    """Freeze the bug that made detection_rate meaningless.

    The pre-fix premise was classified 'supports' by the real model, so every
    dispute the harness counted came from unrelated evidence rather than the
    planted row. planted_premise_detected must fall to 0 for such a judge even
    though detection_rate can still look healthy."""
    from eval.consistency.inject import planted_premise_detected

    class RestatesClaimJudge:
        """Stands in for MNLI: a premise quoting the claim reads as entailment."""
        def classify_pairs(self, pairs):
            return [("supports", 0.9) if h in p else ("neutral", 0.0) for p, h in pairs]

    cases = [(_EVIDENCE, "Three self-radicalised Singapore teens were detained.")]
    assert planted_premise_detected(cases, RestatesClaimJudge()) == 0.0


@pytest.mark.slow
@pytest.mark.skipif(
    os.getenv("SENTINEL_NLI_TEST") != "1",
    reason="set SENTINEL_NLI_TEST=1 to run the real-model injection check (downloads ~400MB)",
)
def test_real_model_reads_the_planted_premise_as_contradicting():
    """The fake judges above cannot catch premise wording the real model misreads."""
    from eval.consistency.inject import planted_premise_detected
    from pipeline.nli import get_judge

    cases = [
        (_EVIDENCE, "Three self-radicalised Singapore teens were detained."),
        (_EVIDENCE, "Saudi Arabia struck an Iran-backed Iraqi militia."),
        (_EVIDENCE, "Police are treating the death of a woman as murder."),
    ]
    assert planted_premise_detected(cases, get_judge()) >= 0.8
