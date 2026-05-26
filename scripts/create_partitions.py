#!/usr/bin/env python3
"""
Create monthly partitions for events_partitioned and hotspots_partitioned tables.

Usage:
    python scripts/create_partitions.py                    # current month + 2 ahead
    python scripts/create_partitions.py --months-ahead 6    # current month + 6 ahead
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from dateutil.relativedelta import relativedelta

import psycopg2


def get_months_to_create(months_ahead: int) -> list[str]:
    """Generate list of YYYYMM strings from current month to N months ahead."""
    months = []
    current = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for i in range(months_ahead + 1):
        dt = current + relativedelta(months=i)
        months.append(dt.strftime("%Y%m"))
    return months


def partition_exists(conn, table_name: str, partition_suffix: str) -> bool:
    """Check if a partition exists for the given table."""
    partition_name = f"{table_name}_{partition_suffix}"
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relname = %s AND n.nspname = 'public'
            )
            """,
            (partition_name,),
        )
        return cur.fetchone()[0]


def create_partition(conn, table_name: str, year_month: str) -> bool:
    """
    Create a partition for the given table and YYYYMM string.

    Returns True if partition was created, False if it already existed.
    """
    partition_name = f"{table_name}_{year_month}"
    year = year_month[:4]
    month = year_month[4:6]

    # PostgreSQL partition bounds
    start_date = f"{year}-{month}-01"
    end_dt = datetime(int(year), int(month), 1) + relativedelta(months=1)
    end_date = end_dt.strftime("%Y-%m-%d")

    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {partition_name}
                PARTITION OF {table_name}
                FOR VALUES FROM (%s) TO (%s)
                """,
                (start_date, end_date),
            )
        return True
    except psycopg2.errors.DuplicateObject:
        return False
    except psycopg2.Error as e:
        print(f"    ERROR creating partition {partition_name}: {e}", file=sys.stderr)
        raise


def create_partitions_for_month(year_month: str, conn) -> list[str]:
    """Create partitions for both events_partitioned and hotspots_partitioned."""
    created = []
    tables = ["events_partitioned", "hotspots_partitioned"]

    for table in tables:
        if partition_exists(conn, table, year_month):
            print(f"  {table}_{year_month}: already exists, skipping")
        else:
            try:
                create_partition(conn, table, year_month)
                print(f"  {table}_{year_month}: created")
                created.append(f"{table}_{year_month}")
            except psycopg2.Error:
                print(f"  {table}_{year_month}: failed", file=sys.stderr)

    return created


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


def _get_env(key: str, default: str) -> str:
    import os
    return os.environ.get(key, default)


def main():
    parser = argparse.ArgumentParser(
        description="Create monthly partitions for Sentinel tables"
    )
    parser.add_argument(
        "--months-ahead",
        type=int,
        default=2,
        help="Number of months ahead to create partitions for (default: 2)",
    )
    args = parser.parse_args()

    months = get_months_to_create(args.months_ahead)
    print(f"Creating partitions for months: {', '.join(months)}")
    print()

    try:
        conn = get_connection()
        try:
            total_created = 0
            for year_month in months:
                print(f"Processing {year_month}:")
                created = create_partitions_for_month(year_month, conn)
                total_created += len(created)
                print()
            print(f"Done. Created {total_created} new partition(s).")
        finally:
            conn.close()
    except psycopg2.OperationalError as e:
        print(f"ERROR: Could not connect to database: {e}", file=sys.stderr)
        sys.exit(1)
    except psycopg2.Error as e:
        print(f"ERROR: Database error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()