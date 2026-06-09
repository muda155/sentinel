"""Consensus worker: hotspot_created -> compute conf_score -> update DB ->
publish llm_needed when conf_score > SENTINEL_LLM_THRESHOLD. Reuses pipeline.scoring."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from api.metrics import METRICS
from pipeline.db import get_pooled_connection
from pipeline.scoring import score_hotspot
from pipeline.workers.base import Worker


class ConsensusWorker(Worker):
    in_stream = "sentinel:hotspot_created"
    group = "cg:consensus"
    out_stream = "sentinel:llm_needed"

    def handle(self, msg_id, data):
        hotspot_id = int(data["hotspot_id"])
        threshold = float(os.getenv("SENTINEL_LLM_THRESHOLD", "40"))
        conn, pool = get_pooled_connection()
        try:
            conf = score_hotspot(conn, hotspot_id)   # computes + persists conf_score
        finally:
            pool.return_connection(conn)
        if conf is not None and conf > threshold:
            METRICS.inc("alerts_total")
            return [{
                "hotspot_id": hotspot_id, "conf_score": float(conf),
                "ts": datetime.now(timezone.utc).isoformat(),
            }]
        return []


def main() -> int:  # pragma: no cover
    ConsensusWorker().run_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
