"""GDELT GKG 2.1 headline enrichment (FR-25).

GDELT publishes a Global Knowledge Graph file alongside every 15-minute export
file. Each GKG row carries the article's ``<PAGE_TITLE>``, keyed by the same URL
the export file stores in ``SOURCEURL``. That gives real headlines for
``events.title`` without scraping and without an API key.
"""
from __future__ import annotations

import csv
import html
import io
import logging
import re

logger = logging.getLogger(__name__)

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
