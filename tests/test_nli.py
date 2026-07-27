"""NLI judge wrapper: label mapping + lazy loading (FR-22)."""
import os

import pytest

from pipeline.nli import NLIJudge, NLIUnavailable, map_label


def test_map_label_normalizes_model_labels():
    assert map_label("entailment") == "supports"
    assert map_label("ENTAILMENT") == "supports"
    assert map_label("contradiction") == "contradicts"
    assert map_label("neutral") == "neutral"
    assert map_label("LABEL_1") == "neutral"  # unknown labels degrade to neutral


def test_missing_backend_raises_nli_unavailable(monkeypatch):
    judge = NLIJudge(model_name="definitely/not-a-real-model-xyz")
    monkeypatch.setattr("pipeline.nli._import_backend", _raise_import_error)
    with pytest.raises(NLIUnavailable):
        judge.classify_pairs([("premise", "hypothesis")])


def _raise_import_error():
    raise ImportError("torch not installed")


@pytest.mark.slow
@pytest.mark.skipif(
    os.getenv("SENTINEL_NLI_TEST") != "1",
    reason="set SENTINEL_NLI_TEST=1 to run the real-model NLI test (downloads ~400MB)",
)
def test_real_model_detects_contradiction():
    judge = NLIJudge()
    results = judge.classify_pairs([
        ("The army advanced 5 km north of the city.",
         "The army advanced north of the city."),
        ("The army advanced 5 km north of the city.",
         "The army retreated and did not advance."),
    ])
    assert results[0][0] == "supports"
    assert results[1][0] == "contradicts"
