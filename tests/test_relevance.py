"""FR-26: semantic relevance primitives (no model download in these tests)."""
import os

import numpy as np
import pytest

from pipeline.relevance import (
    Embedder,
    RelevanceUnavailable,
    max_homogeneity,
    min_peak,
    min_sim,
    relevance_enabled,
)


def test_embedder_raises_relevance_unavailable_on_bad_model():
    embedder = Embedder(model_name="definitely/not-a-real-model-xyz")
    with pytest.raises(RelevanceUnavailable):
        embedder.embed(["hello"])


def test_embedder_does_not_load_until_used():
    # Lazy: constructing must not touch torch/transformers or the network.
    embedder = Embedder(model_name="definitely/not-a-real-model-xyz")
    assert embedder._model is None


def test_relevance_enabled_defaults_true_and_respects_off(monkeypatch):
    monkeypatch.delenv("SENTINEL_RELEVANCE_ENABLED", raising=False)
    assert relevance_enabled() is True
    for off in ("false", "0", "no", "off"):
        monkeypatch.setenv("SENTINEL_RELEVANCE_ENABLED", off)
        assert relevance_enabled() is False


def test_thresholds_read_env_with_documented_defaults(monkeypatch):
    for name in ("SENTINEL_RELEVANCE_MIN_SIM", "SENTINEL_RELEVANCE_MIN_PEAK",
                 "SENTINEL_RELEVANCE_MAX_HOMOGENEITY"):
        monkeypatch.delenv(name, raising=False)
    assert min_sim() == 0.35
    assert min_peak() == 0.15
    assert max_homogeneity() == 0.75
    monkeypatch.setenv("SENTINEL_RELEVANCE_MIN_SIM", "0.5")
    assert min_sim() == 0.5


@pytest.mark.skipif(
    not os.getenv("SENTINEL_RELEVANCE_TEST"),
    reason="SENTINEL_RELEVANCE_TEST not set; skipping real-model test",
)
def test_real_model_embeddings_are_normalised_and_semantic():
    from pipeline.relevance import get_embedder

    vectors = get_embedder().embed([
        "Israeli forces struck targets in Gaza.",
        "The IDF carried out strikes in Gaza.",
        "A rapper testified in his own trial.",
    ])
    assert vectors.shape[0] == 3
    norms = np.linalg.norm(vectors, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)
    paraphrase = float(vectors[0] @ vectors[1])
    unrelated = float(vectors[0] @ vectors[2])
    assert paraphrase > unrelated + 0.2
