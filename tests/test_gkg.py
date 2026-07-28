"""FR-25: GDELT GKG headline extraction (pure functions, no network)."""
import io
import zipfile
from datetime import datetime, timezone

import pytest
import requests

from pipeline.gkg import (
    clean_headline,
    fetch_headlines,
    fetch_headlines_from_gkg_url,
    gkg_enabled,
    gkg_url_for,
    iter_gkg_urls,
    parse_headlines,
)


def test_gkg_url_for_swaps_suffix_on_same_timestamp():
    export = "http://data.gdeltproject.org/gdeltv2/20260727051500.export.CSV.zip"
    assert gkg_url_for(export) == (
        "http://data.gdeltproject.org/gdeltv2/20260727051500.gkg.csv.zip"
    )


def test_gkg_url_for_rejects_non_export_url():
    with pytest.raises(ValueError):
        gkg_url_for("http://data.gdeltproject.org/gdeltv2/20260727051500.mentions.CSV.zip")


def test_clean_headline_unescapes_entities():
    # Deliberately entity-only, no dash: a short trailing "- word" is
    # indistinguishable from site branding and is stripped by design.
    assert clean_headline("Israel &amp; Iran resume talks") == "Israel & Iran resume talks"


def test_clean_headline_collapses_whitespace():
    assert clean_headline("  Army   advances\n north  ") == "Army advances north"


def test_clean_headline_strips_site_name_suffix():
    raw = "Flooding displaces thousands – Winnipeg Free Press"
    assert clean_headline(raw) == "Flooding displaces thousands"


def test_clean_headline_keeps_long_trailing_clause():
    # Suffix stripping is bounded to 40 chars after the dash so real clauses survive.
    raw = "Talks collapse - and the ceasefire agreement is now formally suspended"
    assert clean_headline(raw) == raw


def test_clean_headline_truncates_to_300_chars():
    assert len(clean_headline("word " * 200)) == 300


_ROW_TEMPLATE = [f"c{i}" for i in range(27)]


def _gkg_row(url: str, extras: str) -> str:
    cols = list(_ROW_TEMPLATE)
    cols[4] = url
    cols[26] = extras
    return "\t".join(cols)


def test_parse_headlines_maps_url_to_title():
    csv_text = _gkg_row(
        "https://example.com/a",
        "<PAGE_PRECISEPUBTIMESTAMP>1</PAGE_PRECISEPUBTIMESTAMP>"
        "<PAGE_TITLE>South Korea monitors troop movements</PAGE_TITLE>",
    )
    assert parse_headlines(csv_text) == {
        "https://example.com/a": "South Korea monitors troop movements"
    }


def test_parse_headlines_cleans_each_title():
    csv_text = _gkg_row(
        "https://example.com/b",
        "<PAGE_TITLE>Talks stall &#x2013; again – Winnipeg Free Press</PAGE_TITLE>",
    )
    assert parse_headlines(csv_text) == {"https://example.com/b": "Talks stall – again"}


def test_parse_headlines_skips_rows_without_title():
    csv_text = "\n".join([
        _gkg_row("https://example.com/a", "<PAGE_TITLE>Real headline here</PAGE_TITLE>"),
        _gkg_row("https://example.com/b", "<PAGE_LINKS>none</PAGE_LINKS>"),
    ])
    assert parse_headlines(csv_text) == {"https://example.com/a": "Real headline here"}


def test_parse_headlines_skips_short_and_blank_rows():
    csv_text = "\n".join([
        "too\tshort",
        "",
        _gkg_row("https://example.com/a", "<PAGE_TITLE>Real headline here</PAGE_TITLE>"),
    ])
    assert parse_headlines(csv_text) == {"https://example.com/a": "Real headline here"}


def test_parse_headlines_tolerates_unbalanced_quotes():
    csv_text = _gkg_row(
        'https://example.com/c?q="x',
        '<PAGE_TITLE>Minister says "we will not negotiate"</PAGE_TITLE>',
    )
    assert csv_text.count("\t") == 26
    assert parse_headlines(csv_text) == {
        'https://example.com/c?q="x': 'Minister says "we will not negotiate"'
    }


def test_parse_headlines_ignores_empty_title_tag():
    csv_text = _gkg_row("https://example.com/d", "<PAGE_TITLE>   </PAGE_TITLE>")
    assert parse_headlines(csv_text) == {}


class _FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        return None


def _zipped(csv_text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("20260727051500.gkg.csv", csv_text)
    return buf.getvalue()


def test_fetch_headlines_parses_downloaded_zip(monkeypatch):
    csv_text = _gkg_row(
        "https://example.com/a", "<PAGE_TITLE>Real headline here</PAGE_TITLE>"
    )
    seen = {}

    def fake_get(url, timeout=None):
        seen["url"] = url
        seen["timeout"] = timeout
        return _FakeResponse(_zipped(csv_text))

    monkeypatch.setattr("pipeline.gkg._HTTP_SESSION.get", fake_get)
    result = fetch_headlines(
        "http://data.gdeltproject.org/gdeltv2/20260727051500.export.CSV.zip"
    )
    assert result == {"https://example.com/a": "Real headline here"}
    assert seen["url"].endswith("20260727051500.gkg.csv.zip")
    assert seen["timeout"] == 120


def test_fetch_headlines_honours_timeout_env(monkeypatch):
    monkeypatch.setenv("SENTINEL_GKG_TIMEOUT_S", "7")
    seen = {}

    def fake_get(url, timeout=None):
        seen["timeout"] = timeout
        return _FakeResponse(_zipped(""))

    monkeypatch.setattr("pipeline.gkg._HTTP_SESSION.get", fake_get)
    fetch_headlines_from_gkg_url(
        "http://data.gdeltproject.org/gdeltv2/20260727051500.gkg.csv.zip"
    )
    assert seen["timeout"] == 7


def test_fetch_headlines_returns_empty_on_http_error(monkeypatch):
    def fake_get(url, timeout=None):
        raise requests.HTTPError("404 Not Found")

    monkeypatch.setattr("pipeline.gkg._HTTP_SESSION.get", fake_get)
    assert fetch_headlines(
        "http://data.gdeltproject.org/gdeltv2/20260727051500.export.CSV.zip"
    ) == {}


def test_fetch_headlines_returns_empty_on_zero_byte_file(monkeypatch):
    # GDELT observably serves a 0-byte GKG file when the tick has not finished.
    monkeypatch.setattr(
        "pipeline.gkg._HTTP_SESSION.get", lambda url, timeout=None: _FakeResponse(b"")
    )
    assert fetch_headlines(
        "http://data.gdeltproject.org/gdeltv2/20260727051500.export.CSV.zip"
    ) == {}


def test_fetch_headlines_returns_empty_on_bad_export_url(monkeypatch):
    def boom(url, timeout=None):
        raise AssertionError("must not download for an invalid export URL")

    monkeypatch.setattr("pipeline.gkg._HTTP_SESSION.get", boom)
    assert fetch_headlines("http://example.com/not-a-gdelt-file.txt") == {}


def test_gkg_enabled_defaults_true_and_respects_off(monkeypatch):
    monkeypatch.delenv("SENTINEL_GKG_ENABLED", raising=False)
    assert gkg_enabled() is True
    monkeypatch.setenv("SENTINEL_GKG_ENABLED", "false")
    assert gkg_enabled() is False
    monkeypatch.setenv("SENTINEL_GKG_ENABLED", "0")
    assert gkg_enabled() is False


def test_iter_gkg_urls_starts_at_the_enclosing_quarter_hour():
    now = datetime(2026, 7, 27, 12, 7, 41, tzinfo=timezone.utc)
    first = next(iter(iter_gkg_urls(1, now=now)))
    assert first == (
        "http://data.gdeltproject.org/gdeltv2/20260727120000.gkg.csv.zip"
    )


def test_iter_gkg_urls_yields_96_files_per_day_newest_first():
    now = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
    urls = list(iter_gkg_urls(1, now=now))
    assert len(urls) == 96
    assert urls[1].endswith("20260727114500.gkg.csv.zip")
    assert urls[-1].endswith("20260726121500.gkg.csv.zip")


def test_iter_gkg_urls_scales_with_days():
    now = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
    assert len(list(iter_gkg_urls(3, now=now))) == 288
