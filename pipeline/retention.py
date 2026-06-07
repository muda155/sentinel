"""Monthly partition maintenance and rolling-window retention for events.

Retention is implemented as DROP of partitions older than SENTINEL_RETENTION_DAYS,
per spec Section 6.2.1. Date math is pure and unit-tested; the DB operations are
thin wrappers around it.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, timedelta

logger = logging.getLogger(__name__)

_PARTITION_RE = re.compile(r"^events_(\d{4})_(\d{2})$")


def _add_months(d: date, n: int) -> date:
    month_index = (d.year * 12 + (d.month - 1)) + n
    return date(month_index // 12, month_index % 12 + 1, 1)


def months_to_provision(today: date, ahead: int) -> list[str]:
    """Return 'YYYY_MM' suffixes for the current month plus `ahead` future months."""
    start = date(today.year, today.month, 1)
    return [_add_months(start, i).strftime("%Y_%m") for i in range(ahead + 1)]


def partitions_to_drop(existing: list[str], keep_from: date) -> list[str]:
    """Return partition table names strictly older than the month of `keep_from`."""
    cutoff = (keep_from.year, keep_from.month)
    drop: list[str] = []
    for name in existing:
        m = _PARTITION_RE.match(name)
        if not m:
            continue
        ym = (int(m.group(1)), int(m.group(2)))
        if ym < cutoff:
            drop.append(name)
    return sorted(drop)


def _retention_days() -> int:
    return int(os.getenv("SENTINEL_RETENTION_DAYS", "90"))


def ensure_partitions(conn, today: date | None = None, ahead: int = 3) -> list[str]:
    """Create the current + `ahead` future monthly partitions if missing."""
    today = today or date.today()
    created: list[str] = []
    with conn.cursor() as cur:
        for suffix in months_to_provision(today, ahead):
            start = date(int(suffix[:4]), int(suffix[5:7]), 1)
            end = _add_months(start, 1)
            name = f"events_{suffix}"
            cur.execute(
                f'CREATE TABLE IF NOT EXISTS "{name}" PARTITION OF events '
                f"FOR VALUES FROM (%s) TO (%s)",
                (start, end),
            )
            created.append(name)
    conn.commit()
    return created


def apply_retention(conn, today: date | None = None) -> list[str]:
    """Drop partitions older than the retention window and prune orphan links."""
    today = today or date.today()
    cutoff_date = today - timedelta(days=_retention_days())
    keep_from = date(cutoff_date.year, cutoff_date.month, 1)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.relname FROM pg_inherits i "
            "JOIN pg_class c ON c.oid = i.inhrelid "
            "JOIN pg_class p ON p.oid = i.inhparent "
            "WHERE p.relname = 'events'"
        )
        existing = [row[0] for row in cur.fetchall()]
        to_drop = partitions_to_drop(existing, keep_from)
        for name in to_drop:
            logger.info("Dropping expired partition %s", name)
            cur.execute(f'DROP TABLE IF EXISTS "{name}"')
        # Prune event_hotspot rows whose events no longer exist (FK was removed).
        cur.execute(
            "DELETE FROM event_hotspot eh "
            "WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.event_id = eh.event_id)"
        )
    conn.commit()
    return to_drop