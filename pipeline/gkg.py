"""GDELT GKG 2.1 headline enrichment (FR-25).

GDELT publishes a Global Knowledge Graph file alongside every 15-minute export
file. Each GKG row carries the article's ``<PAGE_TITLE>``, keyed by the same URL
the export file stores in ``SOURCEURL``. That gives real headlines for
``events.title`` without scraping and without an API key.
"""
from __future__ import annotations

import argparse
import csv
import html
import io
import logging
import os
import re
import zipfile
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import requests
from psycopg2.extras import execute_values

from pipeline.db import get_pooled_connection

logger = logging.getLogger(__name__)

# Module-level session so tests that mock ``_HTTP_SESSION.get`` do not conflict
# with tests that mock ``pipeline.ingestion.requests.get`` (they share the same
# global ``requests.get`` function). Not thread-safe — APScheduler uses a thread
# pool so overlapping ticks would share it. Low risk (one ingestion job at a
# time); convert to per-call ``requests.Session()`` if concurrent jobs appear.
_HTTP_SESSION = requests.Session()

GKG_BASE = "http://data.gdeltproject.org/gdeltv2"

_EXPORT_SUFFIX = ".export.CSV.zip"
_GKG_SUFFIX = ".gkg.csv.zip"

# GKG 2.1 is a 27-column tab-delimited file with no header row.
_URL_COLUMN = 4
_EXTRAS_COLUMN = 26
_GKG_COLUMNS = 27

_PAGE_TITLE = re.compile(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>")
# A trailing " - Some Outlet" is site branding, not part of the claim. Bounded to
# 40 characters so a genuine trailing clause is not clipped.
_SITE_SUFFIX = re.compile(r"\s+[-–—|]\s+[^-–—|]{1,40}$")

_MAX_HEADLINE_CHARS = 300

# V2GCAM and V2EXTRASXML exceed Python's default 128 KB field limit. sys.maxsize
# overflows the C long this setter takes on some platforms, so use a literal.
csv.field_size_limit(10_000_000)


def gkg_url_for(export_url: str) -> str:
    """Return the GKG file URL for the same timestamp as ``export_url``."""
    if not export_url.endswith(_EXPORT_SUFFIX):
        raise ValueError(f"Not a GDELT export URL: {export_url}")
    return export_url[: -len(_EXPORT_SUFFIX)] + _GKG_SUFFIX


def clean_headline(raw: str) -> str:
    """Normalize a raw ``<PAGE_TITLE>`` into a usable NLI premise."""
    text = html.unescape(raw)
    text = re.sub(r"\s+", " ", text).strip()
    text = _SITE_SUFFIX.sub("", text).strip()
    return text[:_MAX_HEADLINE_CHARS]


def parse_headlines(csv_text: str) -> dict[str, str]:
    """Map article URL to cleaned headline for every parseable GKG row.

    Rows without a URL or a non-empty ``<PAGE_TITLE>`` are skipped, never raised
    on: a single malformed row must not cost us the rest of the file.
    """
    headlines: dict[str, str] = {}
    reader = csv.reader(
        io.StringIO(csv_text), delimiter="\t", quoting=csv.QUOTE_NONE
    )
    while True:
        try:
            row = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            logger.debug("GKG row unreadable, skipping: %s", exc)
            continue
        if len(row) < _GKG_COLUMNS:
            continue
        url = row[_URL_COLUMN].strip()
        if not url:
            continue
        match = _PAGE_TITLE.search(row[_EXTRAS_COLUMN])
        if not match:
            continue
        headline = clean_headline(match.group(1))
        if headline:
            headlines[url] = headline
    return headlines


def gkg_enabled() -> bool:
    """GKG enrichment is opt-out so an outage can be handled without a redeploy."""
    return os.getenv("SENTINEL_GKG_ENABLED", "true").strip().lower() not in {
        "false", "0", "no", "off",
    }


def _timeout_seconds(timeout: int | None) -> int:
    if timeout is not None:
        return timeout
    return int(os.getenv("SENTINEL_GKG_TIMEOUT_S", "120"))


def fetch_headlines_from_gkg_url(
    gkg_url: str, *, timeout: int | None = None
) -> dict[str, str]:
    """Download and parse one GKG file. Returns {} on any failure, never raises.

    Enrichment is strictly additive: a missing or broken GKG file must degrade to
    Actor1Name titles, not fail the ingestion tick.

    Uses Session().get rather than the module-level requests.get so that
    tests which mock ``pipeline.ingestion.requests.get`` (the global
    ``requests.get``) do not intercept GKG download calls.
    """
    try:
        response = _HTTP_SESSION.get(gkg_url, timeout=_timeout_seconds(timeout))
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = archive.namelist()
            if not names:
                logger.warning("GKG archive is empty: %s", gkg_url)
                return {}
            raw = archive.read(names[0])
        return parse_headlines(raw.decode("utf-8", errors="replace"))
    except Exception as exc:
        logger.warning("GKG fetch failed for %s: %s", gkg_url, exc)
        return {}


def fetch_headlines(export_url: str, *, timeout: int | None = None) -> dict[str, str]:
    """Return {article url: headline} for the GKG file paired with ``export_url``."""
    try:
        gkg_url = gkg_url_for(export_url)
    except ValueError as exc:
        logger.warning("No GKG file derivable: %s", exc)
        return {}
    return fetch_headlines_from_gkg_url(gkg_url, timeout=timeout)


_TICK = timedelta(minutes=15)


def iter_gkg_urls(days: int, *, now: datetime | None = None) -> Iterator[str]:
    """Yield GKG file URLs oldest-first over the last ``days`` days.

    Oldest-first means ``--max-files`` truncates the newest (already-enriched)
    end rather than the oldest end where un-enriched rows live. GDELT publishes
    on a fixed 15-minute grid, so the URLs are derivable without reading
    masterfilelist.txt (which is ~100 MB).
    """
    current = (now or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
    current = current.replace(minute=(current.minute // 15) * 15)
    oldest = current - timedelta(days=days)
    tick = oldest + _TICK
    while tick <= current:
        yield f"{GKG_BASE}/{tick.strftime('%Y%m%d%H%M%S')}.gkg.csv.zip"
        tick += _TICK


# ---------------------------------------------------------------------------
# Backfill CLI (FR-25)
#
# Module-local SQL follows the pipeline/source_country.py --backfill precedent:
# a one-shot maintenance command owns its own statements rather than widening
# pipeline/db.py with queries nothing else calls.
# ---------------------------------------------------------------------------

# GDELT actor names are ALL-CAPS; a real headline contains a lowercase letter.
# This marker needs no schema change and makes the backfill idempotent.
_UNENRICHED = "(title IS NULL OR title !~ '[a-z]')"


def pending_urls(conn, days: int) -> set[str]:
    """Return distinct GDELT article URLs still carrying an actor-name title."""
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT DISTINCT url FROM events
            WHERE source_system = 'GDELT'
              AND url IS NOT NULL
              AND event_date >= now() - make_interval(days => %s)
              AND {_UNENRICHED}
            """,
            (days,),
        )
        return {row[0] for row in cursor.fetchall()}


_PAGE_SIZE = 100


def _apply_titles(conn, batch: list[tuple[str, str]], days: int) -> int:
    """UPDATE titles for matched URLs within the backfill window.

    The un-enriched guard is repeated here so a concurrent ingest cannot
    overwrite a row between SELECT and UPDATE. The ``event_date >= …``
    predicate mirrors ``pending_urls`` so the UPDATE benefits from partition
    pruning. ``cursor.rowcount`` is accumulated per-page because psycopg2's
    ``execute_values`` paginates at 100 rows and ``rowcount`` reflects only
    the last page.
    """
    updated = 0
    with conn.cursor() as cursor:
        for i in range(0, len(batch), _PAGE_SIZE):
            execute_values(
                cursor,
                f"""
                UPDATE events e SET title = v.title
                FROM (VALUES %s) AS v(url, title)
                WHERE e.url = v.url
                  AND e.source_system = 'GDELT'
                  AND e.event_date >= now() - make_interval(days => {days})
                  AND {_UNENRICHED}
                """,
                batch[i : i + _PAGE_SIZE],
            )
            updated += cursor.rowcount
    conn.commit()
    return updated


def backfill(
    conn,
    days: int | None = None,
    *,
    dry_run: bool = False,
    max_files: int | None = None,
) -> dict[str, int]:
    """Rewrite actor-name titles in the recent window with real GKG headlines.

    Walks GKG files newest-first and stops as soon as every pending URL has been
    matched — a full 7-day walk is ~670 files at ~5 MB each.
    """
    if days is None:
        days = int(os.getenv("SENTINEL_GKG_BACKFILL_DAYS", "7"))
    stats = {"files_fetched": 0, "urls_matched": 0, "rows_updated": 0}
    pending = pending_urls(conn, days)
    if not pending:
        logger.info("GKG backfill: nothing to enrich in the last %d days", days)
        return stats

    logger.info("GKG backfill: %d un-enriched URLs in the last %d days",
                len(pending), days)
    for gkg_url in iter_gkg_urls(days):
        if max_files is not None and stats["files_fetched"] >= max_files:
            break
        headlines = fetch_headlines_from_gkg_url(gkg_url)
        stats["files_fetched"] += 1
        batch = [(url, title) for url, title in headlines.items() if url in pending]
        if not batch:
            continue
        stats["urls_matched"] += len(batch)
        pending.difference_update(url for url, _ in batch)
        if not dry_run:
            stats["rows_updated"] += _apply_titles(conn, batch, days)
        if not pending:
            break
    return stats


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="GDELT GKG headline enrichment (FR-25)"
    )
    parser.add_argument(
        "--backfill", action="store_true",
        help="Rewrite actor-name titles in the recent window with GKG headlines",
    )
    parser.add_argument(
        "--days", type=int, default=None,
        help="Backfill window in days (default: SENTINEL_GKG_BACKFILL_DAYS, or 7)",
    )
    parser.add_argument(
        "--max-files", type=int, default=None,
        help="Stop after downloading this many GKG files (~5 MB each)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would be updated without writing",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if not args.backfill:
        parser.error("nothing to do: pass --backfill")
    conn, pool = get_pooled_connection()
    try:
        stats = backfill(
            conn, args.days, dry_run=args.dry_run, max_files=args.max_files
        )
    finally:
        pool.return_connection(conn)
    print(
        f"GKG backfill: files={stats['files_fetched']} "
        f"matched={stats['urls_matched']} updated={stats['rows_updated']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
