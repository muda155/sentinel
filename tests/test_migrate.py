from pathlib import Path

from pipeline.migrate import discover_migrations, parse_version, pending_migrations


def test_parse_version_extracts_leading_number():
    assert parse_version("010_partition_events.sql") == 10
    assert parse_version("001_create_events.sql") == 1


def test_discover_migrations_sorted_by_version(tmp_path: Path):
    (tmp_path / "002_b.sql").write_text("select 2;")
    (tmp_path / "010_c.sql").write_text("select 10;")
    (tmp_path / "001_a.sql").write_text("select 1;")
    found = discover_migrations(tmp_path)
    assert [v for v, _ in found] == [1, 2, 10]


def test_pending_excludes_applied():
    found = [(1, Path("001_a.sql")), (2, Path("002_b.sql")), (10, Path("010_c.sql"))]
    assert [v for v, _ in pending_migrations(found, applied={1, 2})] == [10]


def test_apply_is_idempotent_on_live_db(live_conn, tmp_path):
    from pipeline.migrate import apply_migrations

    (tmp_path / "900_smoke.sql").write_text(
        "CREATE TABLE IF NOT EXISTS _m1_smoke (id int);"
    )
    first = apply_migrations(live_conn, tmp_path)
    second = apply_migrations(live_conn, tmp_path)
    assert 900 in first
    assert second == []  # nothing pending on the second run
    with live_conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS _m1_smoke")
        cur.execute("DELETE FROM schema_migrations WHERE version = 900")
    live_conn.commit()