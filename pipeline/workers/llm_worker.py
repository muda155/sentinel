"""LLM worker: llm_needed -> NIM (Ollama fallback) SITREP -> store -> summary_ready.
Reuses pipeline.llm_verifier (citation validation + fallback unchanged)."""

from __future__ import annotations

from datetime import datetime, timezone

from pipeline.db import get_pooled_connection
from pipeline.llm_verifier import verify_hotspot
from pipeline.workers.base import Worker


class LLMWorker(Worker):
    in_stream = "sentinel:llm_needed"
    group = "cg:llm"
    out_stream = "sentinel:summary_ready"

    def handle(self, msg_id, data):
        hotspot_id = int(data["hotspot_id"])
        conn, pool = get_pooled_connection()
        try:
            summary_id = verify_hotspot(conn, hotspot_id)   # returns llm_summaries.summary_id or None
        finally:
            pool.return_connection(conn)
        if summary_id is None:
            return []   # NIM+Ollama both unavailable -> nothing published; replayable later
        return [{
            "hotspot_id": hotspot_id, "summary_id": int(summary_id),
            "ts": datetime.now(timezone.utc).isoformat(),
        }]


def main() -> int:  # pragma: no cover
    LLMWorker().run_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
