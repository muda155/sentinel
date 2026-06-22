"""Ingestion worker tests. The live-DB test verifies tick() self-heals the
events partition gap (provisions current + future partitions) so a back-dated
or month-rollover row can never abort the batch insert."""
import os
from datetime import date

import pandas as pd
import pytest

from pipeline.retention import months_to_provision
from pipeline.workers import ingestion_worker
from pipeline.workers.ingestion_worker import IngestionWorker

pytestmark = pytest.mark.skipif(
    not os.getenv("SENTINEL_TEST_DB"), reason="needs live PostGIS via SENTINEL_TEST_DB"
)


class _FakeGDELT:
    """Stand-in for the GDELT network ingestor — yields no rows."""

    def run_once(self) -> pd.DataFrame:
        return pd.DataFrame()

    def insert_to_db_returning_ids(self, df, conn) -> list[int]:
        return []


def _partition_exists(conn, name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relname = %s AND n.nspname = 'public'",
            (name,),
        )
        return cur.fetchone() is not None


def test_tick_provisions_missing_future_partition(live_conn, monkeypatch):
    # current+3 months ahead is an empty future partition, safe to drop.
    suffix = months_to_provision(date.today(), ahead=3)[-1]
    name = f"events_{suffix}"
    with live_conn.cursor() as cur:
        cur.execute(f'DROP TABLE IF EXISTS "{name}"')
    live_conn.commit()
    assert not _partition_exists(live_conn, name)

    monkeypatch.setattr(ingestion_worker, "GDELT2Ingestor", _FakeGDELT)
    IngestionWorker().tick()

    assert _partition_exists(live_conn, name), (
        f"{name} should be re-provisioned by tick() before ingesting"
    )
