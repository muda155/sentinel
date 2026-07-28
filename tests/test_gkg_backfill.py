"""FR-25: backfill rewrites actor-name titles with real GKG headlines."""
import pytest

from pipeline import gkg


@pytest.fixture
def seeded_rows(live_conn):
    """Two GDELT rows: one un-enriched (ALL-CAPS), one already enriched."""
    with live_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO events (
                source_system, external_event_id, event_date, cameo_code,
                country_code, url, title, point_geom, grid_cell_id, geo_precision
            ) VALUES
            ('GDELT', 'M7-STALE', now(), '190', 'KS',
             'https://example.com/m7-stale', 'SOUTH KOREAN',
             ST_SetSRID(ST_MakePoint(127.0, 37.5), 4326), NULL, 3),
            ('GDELT', 'M7-FRESH', now(), '190', 'KS',
             'https://example.com/m7-fresh', 'Already a real headline',
             ST_SetSRID(ST_MakePoint(127.0, 37.5), 4326), NULL, 3)
            ON CONFLICT (source_system, external_event_id, event_date) DO NOTHING
            """
        )
    live_conn.commit()
    yield live_conn
    with live_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM events WHERE external_event_id IN ('M7-STALE', 'M7-FRESH')"
        )
    live_conn.commit()


def _titles(conn):
    with conn.cursor() as cur:
        cur.execute(
            """SELECT external_event_id, title FROM events
               WHERE external_event_id IN ('M7-STALE', 'M7-FRESH')"""
        )
        return dict(cur.fetchall())


def test_pending_urls_selects_only_uncapitalised_titles(seeded_rows):
    pending = gkg.pending_urls(seeded_rows, 7)
    assert "https://example.com/m7-stale" in pending
    assert "https://example.com/m7-fresh" not in pending


def test_backfill_rewrites_stale_title_and_leaves_enriched_row(seeded_rows, monkeypatch):
    headline = "South Korea monitors reported troop movements"
    monkeypatch.setattr(gkg, "iter_gkg_urls", lambda days, now=None: iter(["fake-url"]))
    monkeypatch.setattr(
        gkg, "fetch_headlines_from_gkg_url",
        lambda url, timeout=None: {
            "https://example.com/m7-stale": headline,
            "https://example.com/m7-fresh": "SHOULD NOT OVERWRITE",
        },
    )
    stats = gkg.backfill(seeded_rows, days=7)
    assert stats["rows_updated"] == 1
    titles = _titles(seeded_rows)
    assert titles["M7-STALE"] == headline
    assert titles["M7-FRESH"] == "Already a real headline"


def test_backfill_is_idempotent(seeded_rows, monkeypatch):
    headline = "South Korea monitors reported troop movements"
    monkeypatch.setattr(gkg, "iter_gkg_urls", lambda days, now=None: iter(["fake-url"]))
    monkeypatch.setattr(
        gkg, "fetch_headlines_from_gkg_url",
        lambda url, timeout=None: {"https://example.com/m7-stale": headline},
    )
    gkg.backfill(seeded_rows, days=7)
    second = gkg.backfill(seeded_rows, days=7)
    assert second["rows_updated"] == 0
    # files_fetched may be >0 if the DB has other stale rows from live data
    # (accepted as long as rows_updated is 0 — the test's own row is idempotent)
    assert _titles(seeded_rows)["M7-STALE"] == headline


def test_backfill_dry_run_changes_nothing(seeded_rows, monkeypatch):
    monkeypatch.setattr(gkg, "iter_gkg_urls", lambda days, now=None: iter(["fake-url"]))
    monkeypatch.setattr(
        gkg, "fetch_headlines_from_gkg_url",
        lambda url, timeout=None: {"https://example.com/m7-stale": "A real headline"},
    )
    stats = gkg.backfill(seeded_rows, days=7, dry_run=True)
    assert stats["urls_matched"] == 1 and stats["rows_updated"] == 0
    assert _titles(seeded_rows)["M7-STALE"] == "SOUTH KOREAN"


def test_backfill_respects_max_files(seeded_rows, monkeypatch):
    monkeypatch.setattr(
        gkg, "iter_gkg_urls", lambda days, now=None: iter(["u1", "u2", "u3"])
    )
    monkeypatch.setattr(
        gkg, "fetch_headlines_from_gkg_url", lambda url, timeout=None: {}
    )
    stats = gkg.backfill(seeded_rows, days=7, max_files=2)
    assert stats["files_fetched"] == 2


def test_apply_titles_never_updates_unmatched_urls(seeded_rows):
    """The un-enriched guard must stay parenthesised.

    AND binds tighter than OR, so an unparenthesised `title IS NULL OR
    title !~ '[a-z]'` lets the OR branch escape every preceding filter --
    including the e.url = v.url join -- and the UPDATE rewrites every
    ALL-CAPS row in the table regardless of URL.
    """
    updated = gkg._apply_titles(
        seeded_rows, [("https://no-such-url.example/zzz", "INJECTED")], 7
    )
    assert updated == 0
    assert _titles(seeded_rows)["M7-STALE"] == "SOUTH KOREAN"
