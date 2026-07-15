"""DBSCAN noise links (is_noise=true) are bookkeeping (FR-5), not sources:
they must not appear in the SITREP prompt or the /hotspots/{id}/events list.
Both queries filter identically so FR-16 citation numbering stays aligned."""
from __future__ import annotations

import os

import psycopg2
import pytest

from api.queries import fetch_hotspot_events
from pipeline.clustering import cluster_single_cell
from pipeline.llm_verifier import LLMRepository
from tests.helpers_seed import seed_demo_events

pytestmark = pytest.mark.destructive

CELL = "1x1_LAT31_LON34"
TABLES = ("llm_summaries", "event_hotspot", "hotspots", "grid_cells", "events")


def _wipe(conn):
    with conn.cursor() as cur:
        for t in TABLES:
            cur.execute(f"DELETE FROM {t}")
    conn.commit()


@pytest.fixture
def conn():
    dsn = os.getenv("SENTINEL_TEST_DB")
    if not dsn:
        pytest.skip("SENTINEL_TEST_DB not set; skipping live-DB integration test")
    conn = psycopg2.connect(dsn)
    _wipe(conn)
    yield conn
    _wipe(conn)
    conn.close()


def _hotspot_with_noise_link(conn) -> tuple[int, str]:
    seed_demo_events(conn)
    hid = cluster_single_cell(conn, CELL)[0]
    noise_url = "https://noise.example.com/unrelated"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO events (source_system, gdelt_global_event_id, external_event_id,
                event_date, cameo_code, country_code, url, title, point_geom, grid_cell_id)
            VALUES ('GDELT', 9500, '9500', NOW(), '19', 'IL', %s, 'noise',
                    ST_SetSRID(ST_MakePoint(34.9, 31.9), 4326), %s)
            RETURNING event_id
            """,
            (noise_url, CELL),
        )
        noise_event_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO event_hotspot (event_id, hotspot_id, is_noise)"
            " VALUES (%s, %s, true)",
            (noise_event_id, hid),
        )
    conn.commit()
    return hid, noise_url


def test_noise_links_excluded_from_llm_prompt_articles(conn):
    hid, noise_url = _hotspot_with_noise_link(conn)
    articles = LLMRepository(conn).fetch_hotspot_articles(hid)
    assert articles, "non-noise members must remain"
    assert noise_url not in [a["url"] for a in articles]


def test_noise_links_excluded_from_hotspot_events_endpoint(conn):
    hid, noise_url = _hotspot_with_noise_link(conn)
    rows = fetch_hotspot_events(conn, hid)
    assert rows, "non-noise members must remain"
    assert noise_url not in [r["url"] for r in rows]
    # citation numbering stays aligned with the prompt articles
    articles = LLMRepository(conn).fetch_hotspot_articles(hid)
    cited = [r for r in rows if r["citation_index"] is not None]
    assert [r["url"] for r in cited] == [a["url"] for a in articles]
