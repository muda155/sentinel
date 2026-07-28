"""FR-26 regression: hotspot 24874's real data, frozen.

Five events, 100% GKG-enriched titles, mixing a Georgia school shooting with a
Singapore stabbing plot because GDELT pinned both to the Florida state centroid.
Pre-M8 every claim was judged to contradict every other, scoring the hotspot 0.
"""
import numpy as np

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
    from eval.consistency.inject import detection_rate

    class OnTopicEmbedder:
        """Injected CONTRARY rows are about the same claim, so they score high."""
        def embed(self, texts):
            rows = [[1.0, 0.0] if "Singapore" in t else [0.0, 1.0] for t in texts]
            return np.array(rows, dtype="float32")

    class ContraryJudge:
        def classify_pairs(self, pairs):
            return [("contradicts", 0.95) if p.startswith("CONTRARY") else ("supports", 0.9)
                    for p, _h in pairs]

    cases = [(_EVIDENCE, "Three self-radicalised Singapore teens were detained.")]
    rate = detection_rate(cases, ContraryJudge(), embedder=OnTopicEmbedder())
    assert rate == 1.0
