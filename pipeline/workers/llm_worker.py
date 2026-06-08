"""LLM worker: llm_needed -> NIM (Ollama fallback) SITREP -> store -> summary_ready.
Reuses pipeline.llm_verifier (citation validation + fallback unchanged)."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from api.metrics import METRICS
from pipeline.db import get_pooled_connection
from pipeline.llm_verifier import call_nim_api, LLMRepository, build_prompt
from pipeline.workers.base import Worker


class LLMWorker(Worker):
    in_stream = "sentinel:llm_needed"
    group = "cg:llm"
    out_stream = "sentinel:summary_ready"

    def handle(self, msg_id, data):
        hotspot_id = int(data["hotspot_id"])
        conn, pool = get_pooled_connection()
        try:
            repo = LLMRepository(conn)
            articles = repo.fetch_hotspot_articles(hotspot_id)
            if not articles:
                return []
            prompt = build_prompt({"hotspot_id": hotspot_id, "articles": articles})
            endpoint = os.getenv("NVIDIA_NIM_ENDPOINT", "")
            api_key = os.getenv("NVIDIA_NIM_API_KEY", "")
            model = os.getenv("NVIDIA_NIM_MODEL", "meta/llama-3.1-70b-instruct")
            ollama_endpoint = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")

            t0 = time.monotonic()
            result, model_used = call_nim_api(
                prompt, endpoint=endpoint, api_key=api_key, model=model,
                ollama_endpoint=ollama_endpoint,
            )
            elapsed = time.monotonic() - t0
            METRICS.observe("llm_latency_seconds", elapsed)

            if not result or not result.get("summary"):
                return []
            if "nim" not in model_used.lower():
                METRICS.inc("llm_fallback_total")
            repo.save_summary(hotspot_id, result, model=model_used)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT summary_id FROM llm_summaries WHERE hotspot_id=%s ORDER BY created_at DESC LIMIT 1",
                    (hotspot_id,),
                )
                row = cur.fetchone()
            summary_id = int(row[0]) if row else None
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
