import os

import pytest

from api.queries import fetch_search


class _NeverCursor:
    def execute(self, *a, **k):
        raise AssertionError("short queries must not hit the DB")
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


class _NeverConn:
    def cursor(self):
        return _NeverCursor()


@pytest.mark.parametrize("q", ["", "a", " x "])
def test_short_query_returns_empty_groups_without_db(q):
    assert fetch_search(_NeverConn(), q) == {"hotspots": [], "events": [], "sources": []}


pytest_live = pytest.mark.skipif(
    not os.getenv("SENTINEL_TEST_DB"), reason="needs live PostGIS via SENTINEL_TEST_DB"
)


@pytest_live
def test_search_endpoint_groups_and_auth():
    from fastapi.testclient import TestClient

    from api.app import create_app
    from api.auth import create_token

    client = TestClient(create_app())
    assert client.get("/search?q=ukraine").status_code in (401, 403)
    auth = {"Authorization": f"Bearer {create_token(username='test', role='analyst')}"}
    r = client.get("/search?q=ukraine", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"hotspots", "events", "sources"}
    for h in body["hotspots"]:
        assert set(h) >= {"hotspot_id", "name", "lat", "lon", "conf_score",
                          "convergence_score", "alert_level", "event_count",
                          "start_window"}
    for e in body["events"]:
        assert set(e) >= {"event_id", "title", "url", "domain", "event_date", "hotspot"}
        assert set(e["hotspot"]) >= {"hotspot_id", "start_window", "end_window", "created_at",
                                     "consistency_score"}
    for s in body["sources"]:
        assert set(s) >= {"source_id", "domain", "trust_tier", "hotspots"}


@pytest_live
def test_search_hotspot_and_event_carry_start_window(live_conn):
    """FR-15 search embeds Hotspot objects; start_window must survive both the
    name group (_HOTSPOT_SELECT) and the FTS event group (inline dict), or the
    lifespan line disappears when a hotspot is opened from search."""
    from api.queries import fetch_search

    with live_conn.cursor() as cur:
        cur.execute("SELECT register_source(%s, %s)", ("https://searchstart.example/a", None))
        source_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO hotspots (centroid_geom, radius_km, start_window,
                   end_window, event_count, unique_sources, consistency_score, name)
               VALUES (ST_SetSRID(ST_MakePoint(34.45, 31.5), 4326), 5.0,
                       '2026-07-01', '2026-08-01', 1, 1, 62.5, 'StartWindowTestHotspot')
               RETURNING hotspot_id"""
        )
        hid = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO events (source_system, external_event_id, event_date,
                   title, source_id, point_geom)
               VALUES ('GDELT', 'SW-1', NOW(), 'Searchable Title Here', %s,
                       ST_SetSRID(ST_MakePoint(34.45, 31.5), 4326))
               RETURNING event_id""",
            (source_id,),
        )
        event_id = cur.fetchone()[0]
        cur.execute("INSERT INTO event_hotspot (event_id, hotspot_id) VALUES (%s, %s)",
                    (event_id, hid))

    by_name = [h for h in fetch_search(live_conn, "StartWindowTestHotspot")["hotspots"]
               if h["hotspot_id"] == hid]
    assert by_name and by_name[0]["start_window"] is not None
    assert by_name[0]["end_window"] is not None
    assert by_name[0]["created_at"] is not None
    assert by_name[0]["consistency_score"] == 62.5

    by_title = [e["hotspot"] for e in fetch_search(live_conn, "Searchable")["events"]
                if e["hotspot"]["hotspot_id"] == hid]
    assert by_title and by_title[0]["start_window"] is not None
    assert by_title[0]["end_window"] is not None
    assert by_title[0]["created_at"] is not None
    assert by_title[0]["consistency_score"] == 62.5


@pytest_live
def test_search_common_domain_returns_200():
    """Regression: q=com must not 500 when the sources group is non-empty
    (originally broke on a trust_tier type mismatch; tiers are int 1-4 since
    migration 017)."""
    from fastapi.testclient import TestClient

    from api.app import create_app
    from api.auth import create_token

    auth = {"Authorization": f"Bearer {create_token(username='test', role='analyst')}"}
    client = TestClient(create_app())
    r = client.get("/search?q=com", headers=auth)
    assert r.status_code == 200
    for s in r.json()["sources"]:
        assert s["trust_tier"] is None or (
            isinstance(s["trust_tier"], int) and 1 <= s["trust_tier"] <= 4
        )


@pytest_live
def test_search_collapses_one_article_into_one_result(live_conn):
    """One article ingested as several GDELT actor-pair rows filled the
    10-row dropdown with the same headline, and each copy was cited
    separately in the detail panel it opened."""
    from api.queries import fetch_search

    shared_url = "https://dedupe.example/solihull"
    with live_conn.cursor() as cur:
        cur.execute("SELECT register_source(%s, %s)", (shared_url, None))
        source_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO hotspots (centroid_geom, radius_km, start_window,
                   end_window, event_count, unique_sources, name)
               VALUES (ST_SetSRID(ST_MakePoint(34.45, 31.5), 4326), 5.0,
                       now(), now(), 3, 1, 'DedupeSearchHotspot')
               RETURNING hotspot_id"""
        )
        hid = cur.fetchone()[0]
        for i in range(3):
            cur.execute(
                """INSERT INTO events (source_system, external_event_id,
                       event_date, title, url, source_id, point_geom)
                   VALUES ('GDELT', %s, NOW(),
                           'Solihull dedupe drill headline', %s, %s,
                           ST_SetSRID(ST_MakePoint(34.45, 31.5), 4326))
                   RETURNING event_id""",
                (f"DEDUPE-{i}", shared_url, source_id),
            )
            event_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO event_hotspot (event_id, hotspot_id) VALUES (%s, %s)",
                (event_id, hid),
            )

    events = fetch_search(live_conn, "Solihull dedupe drill")["events"]
    matching = [e for e in events if e["url"] == shared_url]
    assert len(matching) == 1, "one article must produce one search result"
    assert matching[0]["report_count"] == 3
    assert matching[0]["hotspot"]["hotspot_id"] == hid
