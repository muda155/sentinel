"""Idempotent SQL migration runner backed by a schema_migrations ledger.

Applies every db/init/NNN_*.sql file whose version is not yet recorded, in
ascending version order, each in its own transaction. Safe to run on every
deploy. Use `baseline` to adopt a database that was already initialised by
docker-entrypoint-initdb.d without re-running historical migrations.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
from pathlib import Path

import psycopg2

logger = logging.getLogger(__name__)

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "db" / "init"
_VERSION_RE = re.compile(r"^(\d+)")


def parse_version(filename: str) -> int:
    match = _VERSION_RE.match(filename)
    if not match:
        raise ValueError(f"Migration filename missing leading version: {filename}")
    return int(match.group(1))


def discover_migrations(init_dir: Path) -> list[tuple[int, Path]]:
    files = [p for p in init_dir.glob("*.sql") if p.is_file()]
    found = [(parse_version(p.name), p) for p in files]
    return sorted(found, key=lambda item: item[0])


def pending_migrations(
    found: list[tuple[int, Path]], applied: set[int]
) -> list[tuple[int, Path]]:
    return [(v, p) for v, p in found if v not in applied]


def _ensure_ledger(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    INTEGER PRIMARY KEY,
                filename   TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    conn.commit()


def _applied_versions(conn) -> set[int]:
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations")
        return {int(row[0]) for row in cur.fetchall()}


def _record(conn, version: int, filename: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO schema_migrations (version, filename) VALUES (%s, %s) "
            "ON CONFLICT (version) DO NOTHING",
            (version, filename),
        )


def apply_migrations(conn, init_dir: Path = DEFAULT_DIR) -> list[int]:
    """Apply all pending migrations in order. Returns the versions applied."""
    _ensure_ledger(conn)
    applied = _applied_versions(conn)
    todo = pending_migrations(discover_migrations(init_dir), applied)
    done: list[int] = []
    for version, path in todo:
        logger.info("Applying migration %s (%s)", version, path.name)
        with conn.cursor() as cur:
            cur.execute(path.read_text())
            _record(conn, version, path.name)
        conn.commit()
        done.append(version)
    return done


def baseline(conn, cutoff: int, init_dir: Path = DEFAULT_DIR) -> list[int]:
    """Mark every migration with version <= cutoff as applied WITHOUT running it.

    Use once on a database already initialised by docker-entrypoint-initdb.d.
    """
    _ensure_ledger(conn)
    versions = [v for v, _ in discover_migrations(init_dir) if v <= cutoff]
    with conn.cursor() as cur:
        for version, path in discover_migrations(init_dir):
            if version <= cutoff:
                cur.execute(
                    "INSERT INTO schema_migrations (version, filename) VALUES (%s, %s) "
                    "ON CONFLICT (version) DO NOTHING",
                    (version, path.name),
                )
    conn.commit()
    return versions


def _connect():
    return psycopg2.connect(
        host=os.getenv("PGHOST", "127.0.0.1"),
        port=int(os.getenv("PGPORT", "6432")),
        dbname=os.getenv("PGDATABASE", "sentinel"),
        user=os.getenv("PGUSER", "sentinel_user"),
        password=os.getenv("PGPASSWORD", "sentinel_pass"),
    )


def main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    parser = argparse.ArgumentParser(description="Sentinel migration runner")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("apply", help="apply pending migrations (default)")
    sub.add_parser("status", help="print applied vs pending versions")
    bl = sub.add_parser("baseline", help="mark migrations <= CUTOFF as applied")
    bl.add_argument("cutoff", type=int)
    args = parser.parse_args()

    conn = _connect()
    try:
        if args.command == "baseline":
            marked = baseline(conn, args.cutoff)
            print(f"Baselined versions: {marked}")
        elif args.command == "status":
            _ensure_ledger(conn)
            applied = _applied_versions(conn)
            found = discover_migrations(DEFAULT_DIR)
            pending = [v for v, _ in pending_migrations(found, applied)]
            print(f"Applied: {sorted(applied)}")
            print(f"Pending: {pending}")
        else:
            done = apply_migrations(conn)
            print(f"Applied versions: {done}" if done else "No pending migrations.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())