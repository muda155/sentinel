#!/usr/bin/env python3
"""
Drop partitions older than the specified retention period.

Usage:
    python scripts/cleanup_old_partitions.py                    # dry-run, 12 months retention
    python scripts/cleanup_old_partitions.py --execute         # actually delete
    python scripts/cleanup_old_partitions.py --retention-months 6 --execute
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from dateutil.relativedelta import relativedelta

import psycopg2


def _get_env(key: str, default: str) -> str:
    import os
    return os.environ.get(key, default)


def get_connection():
    """Get database connection using environment variables."""
    return psycopg2.connect(
        host=_get_env("PGHOST", "127.0.0.1"),
        port=int(_get_env("PGPORT", "5433")),
        dbname=_get_env("PGDATABASE", "sentinel"),
        user=_get_env("PGUSER", "sentinel_user"),
        password=_get_env("PGPASSWORD", "sentinel_pass"),
        connect_timeout=10,
    )


def list_partitions(conn) -> list[dict]:
    """
    List all partitions for events_partitioned and hotspots_partitioned.
    Returns list of dicts with table_name, partition_name, year_month.
    """
    partitions = []
    tables = ["events_partitioned", "hotspots_partitioned"]

    with conn.cursor() as cur:
        for table in tables:
            cur.execute(
                """
                SELECT
                    c.relname AS partition_name,
                    pg_get_expr(c.relpartbound, c.oid) AS partition_bound
                FROM pg_class c
                JOIN pg_inherits i ON c.oid = i.inhrelid
                JOIN pg_class parent ON parent.oid = i.inhparent
                WHERE parent.relname = %s
                  AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
                ORDER BY c.relname
                """,
                (table,),
            )
            for row in cur.fetchall():
                partition_name = row[0]
                bound = row[1]
                # Extract YYYYMM from partition name (e.g., events_partitioned_202405)
                if "_20" in partition_name:
                    idx = partition_name.index("_20")
                    year_month = partition_name[idx + 1 : idx + 7]
                    if year_month.isdigit() and len(year_month) == 6:
                        partitions.append(
                            {
                                "table": table,
                                "partition": partition_name,
                                "year_month": year_month,
                            }
                        )
    return partitions


def filter_expired(partitions: list[dict], retention_months: int) -> list[dict]:
    """Filter partitions older than retention period."""
    current = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    cutoff = current - relativedelta(months=retention_months)
    cutoff_str = cutoff.strftime("%Y%m")

    expired = []
    for p in partitions:
        if p["year_month"] < cutoff_str:
            expired.append(p)
    return expired


def detach_partition(conn, partition_name: str, table: str) -> bool:
    """Detach partition from parent table before dropping."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"ALTER TABLE {table} DETACH PARTITION {partition_name}"
            )
        return True
    except psycopg2.Error:
        return False


def drop_partition(conn, partition_name: str) -> bool:
    """Drop the partition table."""
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {partition_name}")
        return True
    except psycopg2.Error as e:
        print(f"    ERROR dropping {partition_name}: {e}", file=sys.stderr)
        return False


def delete_partition(conn, partition_name: str, table: str, execute: bool) -> bool:
    """
    Delete a partition. If execute=True, detach and drop.
    Returns True if partition was deleted, False if skipped or failed.
    """
    if not execute:
        return False

    # Detach first if attached
    if detach_partition(conn, partition_name, table):
        print(f"    detached from {table}")
    else:
        # Not attached, just drop
        pass

    if drop_partition(conn, partition_name):
        print(f"    dropped")
        return True
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Clean up old partitions from Sentinel tables"
    )
    parser.add_argument(
        "--retention-months",
        type=int,
        default=12,
        help="Number of months to retain (partitions older than this will be deleted, default: 12)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute deletion (without this flag, runs in dry-run mode)",
    )
    args = parser.parse_args()

    mode = "DRY-RUN" if not args.execute else "EXECUTE"
    print(f"MODE: {mode}")
    print(f"Retention: {args.retention_months} months")
    print()

    try:
        conn = get_connection()
        try:
            # List all partitions
            all_partitions = list_partitions(conn)

            # Filter to expired ones
            expired = filter_expired(all_partitions, args.retention_months)

            if not expired:
                print("No expired partitions found.")
                return

            # Show what will be deleted
            print(f"Partitions to be deleted ({len(expired)}):")
            for p in sorted(expired, key=lambda x: (x["table"], x["year_month"])):
                print(f"  - {p['partition']} ({p['table']}, {p['year_month']})")
            print()

            if args.execute:
                # Group by partition name to avoid double-processing
                seen = set()
                deleted_count = 0

                for p in sorted(expired, key=lambda x: x["partition"]):
                    if p["partition"] in seen:
                        continue
                    seen.add(p["partition"])

                    print(f"Deleting {p['partition']}:")
                    if delete_partition(conn, p["partition"], p["table"], execute=True):
                        deleted_count += 1

                conn.commit()
                print()
                print(f"Done. Deleted {deleted_count} partition(s).")
            else:
                print("Run with --execute to actually delete these partitions.")

        finally:
            conn.close()

    except psycopg2.OperationalError as e:
        print(f"ERROR: Could not connect to database: {e}", file=sys.stderr)
        sys.exit(1)
    except psycopg2.Error as e:
        print(f"ERROR: Database error: {e}", file=sys.stderr)
        conn.rollback()
        sys.exit(1)


if __name__ == "__main__":
    main()