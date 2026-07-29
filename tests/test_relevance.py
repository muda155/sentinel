"""FR-26: semantic relevance primitives (no model download in these tests)."""
import os

import numpy as np
import pytest

from pipeline.relevance import (
    Embedder,
    RelevanceUnavailable,
    evidence_homogeneity,
    max_homogeneity,
    min_peak,
    min_sim,
    relevance_enabled,
    similarity_matrix,
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


class FakeEmbedder:
    """Maps each text to a fixed unit vector so similarities are exact.

    'a…' texts are one topic, 'b…' texts an orthogonal topic.
    """
    def embed(self, texts):
        rows = []
        for text in texts:
            if text.startswith("a"):
                rows.append([1.0, 0.0])
            elif text.startswith("b"):
                rows.append([0.0, 1.0])
            else:
                rows.append([0.7071067811865476, 0.7071067811865476])
        return np.array(rows, dtype="float32")


def test_similarity_matrix_shape_and_values():
    sim = similarity_matrix(["a claim"], ["a evidence", "b evidence"], FakeEmbedder())
    assert sim.shape == (1, 2)
    assert sim[0][0] == pytest.approx(1.0, abs=1e-5)
    assert sim[0][1] == pytest.approx(0.0, abs=1e-5)


def test_similarity_matrix_handles_multiple_claims():
    sim = similarity_matrix(
        ["a one", "b two"], ["a ev", "b ev", "mixed ev"], FakeEmbedder()
    )
    assert sim.shape == (2, 3)
    assert sim[1][1] == pytest.approx(1.0, abs=1e-5)
    assert sim[1][0] == pytest.approx(0.0, abs=1e-5)


def test_similarity_matrix_empty_inputs():
    assert similarity_matrix([], ["a ev"], FakeEmbedder()).shape == (0, 1)
    assert similarity_matrix(["a claim"], [], FakeEmbedder()).shape == (1, 0)


def test_evidence_homogeneity_single_row_is_one():
    # A single row is trivially homogeneous; the vacuity guard relies on this
    # so a lone evidence row can never trip the filter.
    assert evidence_homogeneity(["a only"], FakeEmbedder()) == 1.0
    assert evidence_homogeneity([], FakeEmbedder()) == 1.0


def test_evidence_homogeneity_identical_topic_is_high():
    value = evidence_homogeneity(["a one", "a two", "a three"], FakeEmbedder())
    assert value == pytest.approx(1.0, abs=1e-5)


def test_evidence_homogeneity_two_topics_is_low():
    # 3 'a' rows + 2 'b' rows: median of the off-diagonal pairs is 0.0
    value = evidence_homogeneity(
        ["a one", "a two", "a three", "b one", "b two"], FakeEmbedder()
    )
    assert value < 0.75
