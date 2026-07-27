"""Local CPU NLI cross-encoder for claim/evidence entailment (FR-22).

Lazy-loads a HuggingFace sequence-classification model. Model files are
downloaded once to the HF cache and used offline afterwards. Any import or
load failure raises NLIUnavailable so the consistency engine can skip
gracefully - the pipeline must never block on this module."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("sentinel.nli")

DEFAULT_MODEL = "cross-encoder/nli-deberta-v3-base"
_BATCH_SIZE = 16
_MAX_LENGTH = 512

_LABELS = {"entailment": "supports", "contradiction": "contradicts", "neutral": "neutral"}


class NLIUnavailable(RuntimeError):
    """Raised when the NLI backend (torch/transformers/model) cannot be used."""


def map_label(raw: str) -> str:
    return _LABELS.get(str(raw).strip().lower(), "neutral")


def _import_backend():
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    return torch, AutoTokenizer, AutoModelForSequenceClassification


class NLIJudge:
    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or os.getenv("SENTINEL_NLI_MODEL", DEFAULT_MODEL)
        self._tokenizer = None
        self._model = None
        self._torch = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        try:
            torch, AutoTokenizer, AutoModel = _import_backend()
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModel.from_pretrained(self.model_name)
            self._model.eval()
            self._torch = torch
        except Exception as exc:
            raise NLIUnavailable(f"NLI backend unavailable ({self.model_name}): {exc}") from exc

    def classify_pairs(self, pairs: list[tuple[str, str]]) -> list[tuple[str, float]]:
        """(premise, hypothesis) pairs -> (relation, probability) per pair."""
        self._ensure_loaded()
        torch = self._torch
        id2label = self._model.config.id2label
        results: list[tuple[str, float]] = []
        for start in range(0, len(pairs), _BATCH_SIZE):
            batch = pairs[start:start + _BATCH_SIZE]
            enc = self._tokenizer(
                [p for p, _ in batch], [h for _, h in batch],
                padding=True, truncation=True, max_length=_MAX_LENGTH,
                return_tensors="pt",
            )
            with torch.no_grad():
                logits = self._model(**enc).logits
            probs = torch.softmax(logits, dim=-1)
            top = probs.argmax(dim=-1)
            for i in range(len(batch)):
                idx = int(top[i])
                results.append((map_label(id2label[idx]), float(probs[i][idx])))
        return results


_judge: NLIJudge | None = None


def get_judge() -> NLIJudge:
    global _judge
    if _judge is None:
        _judge = NLIJudge()
    return _judge
