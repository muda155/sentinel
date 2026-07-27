"""LLM worker: llm_needed -> NIM (Ollama fallback) SITREP -> store -> summary_ready.
Reuses pipeline.llm_verifier (citation validation + fallback unchanged)."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

from api.metrics import METRICS
from pipeline.db import get_pooled_connection
from pipeline.llm_verifier import generate_sitrep
from pipeline.workers.base import Worker

logger = logging.getLogger("sentinel.llm_worker")


class LLMWorker(Worker):
    in_stream = "sentinel:llm_needed"
    group = "cg:llm"
    out_stream = "sentinel:summary_ready"

    def handle(self, msg_id, data):
        hotspot_id = int(data["hotspot_id"])
        conn, pool = get_pooled_connection()
        try:
            from pipeline.llm_verifier import LLMRepository

            repo = LLMRepository(conn)
            if repo.summary_exists(hotspot_id):
                return []

            endpoint = os.getenv("NVIDIA_NIM_ENDPOINT", "")
            api_key = os.getenv("NVIDIA_NIM_API_KEY", "")
            model = os.getenv("NVIDIA_NIM_MODEL", "meta/llama-3.3-70b-instruct")
            ollama_endpoint = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")

            t0 = time.monotonic()
            try:
                summary_id, model_used = generate_sitrep(
                    conn, hotspot_id, endpoint=endpoint, api_key=api_key,
                    model=model, ollama_endpoint=ollama_endpoint,
                )
            except Exception as exc:
                METRICS.inc("llm_failed_total")
                logger.warning("LLM generation failed for hotspot %s: %s", hotspot_id, exc)
                return []
            elapsed = time.monotonic() - t0
            METRICS.observe("llm_latency_seconds", elapsed)
            if summary_id is None:
                return []
            if model_used and "ollama" in model_used.lower():
                METRICS.inc("llm_fallback_total")
        finally:
            pool.return_connection(conn)
        if summary_id is None:
            return []
        return [{
            "hotspot_id": hotspot_id, "summary_id": int(summary_id),
            "ts": datetime.now(timezone.utc).isoformat(),
        }]


def main() -> int:  # pragma: no cover
    LLMWorker().run_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
