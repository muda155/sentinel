"""Semantic relevance gating for the consistency engine (FR-26).

The NLI cross-encoder in ``pipeline/nli.py`` is trained on premise/hypothesis
pairs that describe the same scene. Given two texts about unrelated events it
returns "contradiction" by construction, not "neutral". This module supplies the
missing aboutness signal so off-scene pairs are never asked the question.

Lazy-loads a HuggingFace embedding model; any import or load failure raises
RelevanceUnavailable so the engine can skip rather than judge ungated."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("sentinel.relevance")

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_BATCH_SIZE = 32
_MAX_LENGTH = 256


class RelevanceUnavailable(RuntimeError):
    """Raised when the embedding backend (torch/transformers/model) cannot be used."""


def relevance_enabled() -> bool:
    """Opt-out switch. Disabling reverts to M6's known-degraded ungated judging."""
    return os.getenv("SENTINEL_RELEVANCE_ENABLED", "true").strip().lower() not in {
        "false", "0", "no", "off",
    }


def min_sim() -> float:
    return float(os.getenv("SENTINEL_RELEVANCE_MIN_SIM", "0.35"))


def min_peak() -> float:
    return float(os.getenv("SENTINEL_RELEVANCE_MIN_PEAK", "0.15"))


def max_homogeneity() -> float:
    return float(os.getenv("SENTINEL_RELEVANCE_MAX_HOMOGENEITY", "0.75"))


def _import_backend():
    import numpy as np
    import torch
    from transformers import AutoModel, AutoTokenizer

    return np, torch, AutoTokenizer, AutoModel


class Embedder:
    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or os.getenv("SENTINEL_RELEVANCE_MODEL", DEFAULT_MODEL)
        self._tokenizer = None
        self._model = None
        self._torch = None
        self._np = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        try:
            np, torch, AutoTokenizer, AutoModel = _import_backend()
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModel.from_pretrained(self.model_name)
            self._model.eval()
            self._torch = torch
            self._np = np
        except Exception as exc:
            raise RelevanceUnavailable(
                f"Embedding backend unavailable ({self.model_name}): {exc}"
            ) from exc

    def embed(self, texts: list[str]):
        """Return an (n, dim) L2-normalised float array, one row per text."""
        self._ensure_loaded()
        torch = self._torch
        np = self._np
        if not texts:
            return np.zeros((0, 1), dtype="float32")
        vectors = []
        for start in range(0, len(texts), _BATCH_SIZE):
            batch = texts[start:start + _BATCH_SIZE]
            enc = self._tokenizer(
                batch, padding=True, truncation=True,
                max_length=_MAX_LENGTH, return_tensors="pt",
            )
            with torch.no_grad():
                hidden = self._model(**enc).last_hidden_state
            # Mean-pool over real tokens only, then L2-normalise. This is what
            # the sentence-transformers wrapper does for this model.
            mask = enc["attention_mask"].unsqueeze(-1).float()
            pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
            pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
            vectors.append(pooled.numpy())
        return np.vstack(vectors)


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder


def similarity_matrix(claim_texts: list[str], evidence_texts: list[str], embedder):
    """Cosine similarity of every claim against every evidence row.

    Vectors are already L2-normalised, so the dot product is the cosine."""
    import numpy as np

    if not claim_texts:
        return np.zeros((0, len(evidence_texts)), dtype="float32")
    if not evidence_texts:
        return np.zeros((len(claim_texts), 0), dtype="float32")
    claims = embedder.embed(claim_texts)
    evidence = embedder.embed(evidence_texts)
    return claims @ evidence.T


def evidence_homogeneity(evidence_texts: list[str], embedder) -> float:
    """Median pairwise similarity among evidence rows, diagonal excluded.

    1.0 for fewer than two rows: a single row is trivially one topic, and the
    vacuity filter must never fire in that case."""
    import numpy as np

    if len(evidence_texts) < 2:
        return 1.0
    vectors = embedder.embed(evidence_texts)
    sim = vectors @ vectors.T
    upper = sim[np.triu_indices(len(evidence_texts), k=1)]
    return float(np.median(upper))
