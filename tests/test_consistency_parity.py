"""FR-22(d) claim value: the Python engine and its TypeScript port must agree.

`pipeline/consistency.py:claim_value` is duplicated as `claimValue` in
`frontend-next/lib/window-consistency.ts`, because FR-28 recomputes the score
client-side to check it against the published one. A one-sided edit does not
raise anywhere: `consistencyTrusted()` simply starts failing every check and
CompareDialog degrades to counts-only, silently and permanently.

Both sides therefore assert against one committed fixture. This file is the
generator; regenerate with `python -m tests.test_consistency_parity --regenerate`
after any deliberate formula change, and the vitest suite will fail until the
port is updated to match.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.consistency import ClaimVerdict, claim_value

FIXTURE = Path(__file__).parent / "fixtures" / "claim_value_parity.json"


def _cases() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


def _verdict(case: dict) -> ClaimVerdict:
    return ClaimVerdict(text="c", status=case["status"], support=case["support"],
                        dispute=case["dispute"],
                        weight=max(case["support"] + case["dispute"], 0.1))


def test_fixture_exists_and_covers_every_status():
    cases = _cases()
    assert len(cases) >= 30
    assert {c["status"] for c in cases} == {"corroborated", "uncorroborated", "disputed"}
    # the 0/0 branch and a dispute-only claim must both be represented, or the
    # port could diverge on exactly the cases that matter and stay green
    assert any(c["support"] == 0 and c["dispute"] == 0 for c in cases)
    assert any(c["support"] == 0 and c["dispute"] > 0 for c in cases)


@pytest.mark.parametrize("case", _cases(),
                         ids=lambda c: f"{c['status']}-s{c['support']}-d{c['dispute']}")
def test_python_claim_value_matches_the_parity_fixture(case):
    assert claim_value(_verdict(case)) == pytest.approx(case["value"], abs=1e-12)


def test_fixture_weights_match_the_engine_weight_rule():
    """The fixture also pins w = max(support+dispute, 0.1); the TS port reuses
    it, so a drift in the weight rule is caught here too."""
    for case in _cases():
        assert case["weight"] == pytest.approx(
            max(case["support"] + case["dispute"], 0.1))


def _regenerate() -> int:  # pragma: no cover - maintenance entry point
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for case in payload["cases"]:
        case["weight"] = max(case["support"] + case["dispute"], 0.1)
        case["value"] = claim_value(_verdict(case))
    FIXTURE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"regenerated {len(payload['cases'])} cases in {FIXTURE}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    if "--regenerate" in sys.argv:
        raise SystemExit(_regenerate())
    raise SystemExit("pass --regenerate to rewrite the fixture")
