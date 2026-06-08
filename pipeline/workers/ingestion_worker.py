"""Ingestion worker: GDELT (+ACLED daily) -> DB -> publish event IDs.

Reuses the monolith's ingestion path verbatim (pipeline.ingestion), so output
is identical to pipeline.py Step 1/2. Source-style worker: driven by tick()."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

from pipeline.db import get_pooled_connection
from pipeline.ingestion import GDELT2Ingestor
from pipeline.streams import StreamBus

logger = logging.getLogger(__name__)
OUT_STREAM = "sentinel:ingested_events"


class IngestionWorker:
    def __init__(self, bus: StreamBus | None = None) -> None:
        self.bus = bus or StreamBus()

    def tick(self) -> int:
        """Run one ingestion batch; publish inserted IDs. Returns rows inserted."""
        ingestor = GDELT2Ingestor()
        military_df = ingestor.run_once()
        conn, pool = get_pooled_connection()
        try:
            event_ids = ingestor.insert_to_db_returning_ids(military_df, conn)
        finally:
            pool.return_connection(conn)
        if event_ids:
            self.bus.publish(
                OUT_STREAM,
                {
                    "batch_id": str(uuid.uuid4()),
                    "event_ids": event_ids,
                    "ts": datetime.now(timezone.utc).isoformat(),
                },
            )
        logger.info("ingestion tick complete", extra={"inserted": len(event_ids)})
        return len(event_ids)


def main() -> int:  # pragma: no cover
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    w = IngestionWorker()
    interval = int(os.getenv("SENTINEL_POLL_INTERVAL_S", "900"))
    while True:
        try:
            w.tick()
        except Exception:
            logging.exception("ingestion tick failed")
        import time
        time.sleep(interval)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
