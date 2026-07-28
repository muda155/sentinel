"""FR-25: GDELT GKG headline extraction (pure functions, no network)."""
import pytest

from pipeline.gkg import clean_headline, gkg_url_for, parse_headlines


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
