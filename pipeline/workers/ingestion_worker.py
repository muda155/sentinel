"""Ingestion worker: GDELT (+ACLED daily) -> DB -> publish event IDs.

Reuses the monolith's ingestion path (pipeline.ingestion), so output is
identical to pipeline.py Step 1/2. Source-style worker: driven by tick()."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

from pipeline.db import get_pooled_connection
from pipeline.ingestion import ACLEDIngestor, GDELT2Ingestor
from pipeline.streams import StreamBus

logger = logging.getLogger(__name__)
OUT_STREAM = "sentinel:ingested_events"


class IngestionWorker:
    def __init__(self, bus: StreamBus | None = None) -> None:
        self.bus = bus or StreamBus()

    def tick(self) -> int:
        """Run one ingestion batch (GDELT + ACLED); publish inserted IDs. Returns total rows inserted."""
        conn, pool = get_pooled_connection()
        try:
            inserted = 0
            event_ids: list[int] = []
            # Step 1: GDELT
            ingestor = GDELT2Ingestor()
            military_df = ingestor.run_once()
            event_ids = ingestor.insert_to_db_returning_ids(military_df, conn)
            inserted += len(event_ids)

            # Step 2: ACLED (non-fatal — per monolith pipeline.py Step 2)
            if os.getenv("ACLED_EMAIL") and os.getenv("ACLED_PASSWORD"):
                try:
                    acled_days = int(os.getenv("SENTINEL_ACLED_FETCH_DAYS", "7"))
                    acled = ACLEDIngestor()
                    acled_df = acled.fetch_events(days=acled_days)
                    acled_inserted = acled.insert_to_db(acled_df, conn)
                    inserted += acled_inserted
                    logger.info("ACLED ingestion complete", extra={"acled_inserted": acled_inserted})
                except Exception:
                    logger.warning("ACLED ingestion failed (continuing with GDELT-only)", exc_info=True)
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
        logger.info("ingestion tick complete", extra={"inserted": inserted})
        return inserted


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
