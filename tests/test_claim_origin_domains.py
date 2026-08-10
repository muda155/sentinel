"""claims.origin_domains must survive consensus -> save -> fetch (FR-28)."""
from pipeline.consistency import EvidenceJudgment, ExtractedClaim, consensus


def _evidence():
    return [
        {"citation_index": 1, "domain": "a.com", "trust_score": 0.9},
        {"citation_index": 2, "domain": "b.com", "trust_score": 0.8},
        {"citation_index": 3, "domain": "c.com", "trust_score": 0.7},
    ]


def test_consensus_records_the_origin_domains_it_excluded():
    claims = [ExtractedClaim(text="Shelling reported downtown.", source_indices=[1])]
    judgments = [[
        EvidenceJudgment(event_id=11, citation_index=1, domain="a.com", relation="supports", probability=0.95),
        EvidenceJudgment(event_id=12, citation_index=2, domain="b.com", relation="supports", probability=0.91),
    ]]
    verdict = consensus(claims, _evidence(), judgments)[0]
    assert verdict.origin_domains == ["a.com"]


def test_origin_domains_is_empty_when_the_claim_cites_nothing():
    claims = [ExtractedClaim(text="Shelling reported downtown.", source_indices=[])]
    judgments = [[
        EvidenceJudgment(event_id=11, citation_index=1, domain="a.com", relation="supports", probability=0.95),
    ]]
    verdict = consensus(claims, _evidence(), judgments)[0]
    assert verdict.origin_domains == []
