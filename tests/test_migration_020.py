"""Migration 020 contract: enrichment columns + claims tables exist (FR-21/FR-22)."""
from pathlib import Path

from pipeline.migrate import apply_migrations


def _columns(conn, table: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (table,),
        )
        return {r[0] for r in cur.fetchall()}


def test_migration_020_creates_schema(live_conn):
    apply_migrations(live_conn, Path("db/init"))
    assert {
        "actor1_name", "actor2_name", "goldstein_scale", "avg_tone",
        "num_sources", "notes", "fatalities",
    } <= _columns(live_conn, "events")
    assert "consistency_score" in _columns(live_conn, "hotspots")
    assert {"claim_id", "hotspot_id", "claim_text", "status", "consensus_weight"} <= _columns(
        live_conn, "claims"
    )
    assert {"claim_id", "event_id", "relation", "probability"} <= _columns(
        live_conn, "claim_evidence"
    )


def test_migration_020_is_idempotent(live_conn):
    apply_migrations(live_conn, Path("db/init"))
    with live_conn.cursor() as cur:
        cur.execute("DELETE FROM schema_migrations WHERE version = 20")
    apply_migrations(live_conn, Path("db/init"))  # must not raise
