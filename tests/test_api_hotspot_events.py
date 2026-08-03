import os
from datetime import datetime, timezone

import pytest

from api.queries import assign_citation_indices


def _row(event_id, url, date):
    return {"event_id": event_id, "url": url, "title": f"t{event_id}",
            "event_date": date, "source_system": "GDELT",
            "event_type_label": "military_conflict",
            "trust_tier": None, "trust_score": 0.4}


def test_citation_indices_match_llm_prompt_order():
    d1 = datetime(2026, 6, 10, 12, tzinfo=timezone.utc)
    d2 = datetime(2026, 6, 10, 11, tzinfo=timezone.utc)
    rows = [
        _row(9, "https://a.example/x", d1),
        _row(5, "https://b.example/y", d2),
        _row(3, None, d1),
        _row(2, "", d2),
    ]
    out = assign_citation_indices(rows)
    assert [(r["event_id"], r["citation_index"]) for r in out] == [
        (9, 1), (5, 2), (3, None), (2, None),
    ]
    assert out[0]["domain"] == "a.example"
    assert out[2]["domain"] == ""


def test_citation_indices_empty():
    assert assign_citation_indices([]) == []


pytest_live = pytest.mark.skipif(
    not os.getenv("SENTINEL_TEST_DB"), reason="needs live PostGIS via SENTINEL_TEST_DB"
)


@pytest_live
def test_hotspot_events_endpoint_shape_and_404():
    from fastapi.testclient import TestClient

    from api.app import create_app
    from api.auth import create_token

    auth = {"Authorization": f"Bearer {create_token(username='test', role='analyst')}"}
    client = TestClient(create_app())
    assert client.get("/hotspots/999999999/events", headers=auth).status_code == 404
    hotspots = client.get("/hotspots?limit=1", headers=auth).json()
    if hotspots:
        hid = hotspots[0]["hotspot_id"]
        r = client.get(f"/hotspots/{hid}/events", headers=auth)
        assert r.status_code == 200
        for ev in r.json():
            assert set(ev) >= {"event_id", "title", "url", "domain", "source_system",
                               "event_type_label", "event_date", "trust_tier",
                               "trust_score", "citation_index"}


@pytest_live
def test_hotspot_events_expose_severity_fields(live_conn):
    """FR-21 fields are ingested (pipeline/ingestion.py) but were never
    SELECTed, so the UI could not show why a hotspot matters."""
    from api import queries
    from tests.helpers_seed import seed_demo_events

    seed_demo_events(live_conn)
    with live_conn.cursor() as cur:
        cur.execute(
            """UPDATE events SET goldstein_scale = -8.0, avg_tone = -5.25,
                                 num_sources = 12, fatalities = 3
               WHERE external_event_id = '9001'"""
        )
        cur.execute(
            """INSERT INTO hotspots (centroid_geom, radius_km, start_window,
                   end_window, event_count, unique_sources)
               VALUES (ST_SetSRID(ST_MakePoint(34.45, 31.5), 4326), 5.0,
                       now(), now(), 1, 1)
               RETURNING hotspot_id"""
        )
        hid = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO event_hotspot (event_id, hotspot_id)
               SELECT event_id, %s FROM events WHERE external_event_id = '9001'""",
            (hid,),
        )

    events = queries.fetch_hotspot_events(live_conn, hid)
    target = [e for e in events if e.get("num_sources") == 12]
    assert target, "severity columns missing from payload"
    e = target[0]
    assert e["goldstein_scale"] == -8.0
    assert round(e["avg_tone"], 2) == -5.25
    assert e["fatalities"] == 3


def _seed_hotspot_with_duplicate_article(conn):
    """Three linked events over two distinct articles: alpha is ingested
    twice (the GDELT actor-pair duplicate), bravo once. Returns the
    hotspot_id plus the two URLs.

    now() is the transaction timestamp, so all three rows share an
    event_date and the FR-16 ORDER BY falls through to event_id DESC:
    newest-inserted is citation [1]."""
    alpha = "https://alpha.example/duplicated-story"
    bravo = "https://bravo.example/other-story"
    with conn.cursor() as cur:
        cur.execute("SELECT register_source(%s, %s)", (alpha, None))
        alpha_source = cur.fetchone()[0]
        cur.execute("SELECT register_source(%s, %s)", (bravo, None))
        bravo_source = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO hotspots (centroid_geom, radius_km, start_window,
                   end_window, event_count, unique_sources)
               VALUES (ST_SetSRID(ST_MakePoint(34.45, 31.5), 4326), 5.0,
                       now(), now(), 3, 2)
               RETURNING hotspot_id"""
        )
        hid = cur.fetchone()[0]
        for ext, title, url, source_id in [
            ("PH3DUP-A1", "Alpha reports the strike", alpha, alpha_source),
            ("PH3DUP-A2", "Alpha reports the strike", alpha, alpha_source),
            ("PH3DUP-B1", "Bravo reports the strike", bravo, bravo_source),
        ]:
            cur.execute(
                """INSERT INTO events (source_system, external_event_id,
                       event_date, title, url, source_id, point_geom)
                   VALUES ('GDELT', %s, NOW(), %s, %s, %s,
                           ST_SetSRID(ST_MakePoint(34.45, 31.5), 4326))
                   RETURNING event_id""",
                (ext, title, url, source_id),
            )
            cur.execute(
                "INSERT INTO event_hotspot (event_id, hotspot_id) VALUES (%s, %s)",
                (cur.fetchone()[0], hid),
            )
    return hid, alpha, bravo


@pytest_live
def test_duplicate_urls_collapse_to_one_citation(live_conn):
    """GDELT's one-row-per-actor-pair inflated the sources list: the same
    article was cited under several numbers and read as corroboration."""
    from api import queries

    hid, alpha, bravo = _seed_hotspot_with_duplicate_article(live_conn)

    rows = queries.fetch_hotspot_events(live_conn, hid)
    assert [r["url"] for r in rows] == [bravo, alpha], "FR-16 order must survive"

    matching = [r for r in rows if r["url"] == alpha]
    assert len(matching) == 1, "one article must produce one citation"
    assert matching[0]["duplicate_count"] == 2
    assert [r for r in rows if r["url"] == bravo][0]["duplicate_count"] == 1

    indices = [r["citation_index"] for r in rows if r["citation_index"] is not None]
    assert indices == [1, 2], "citation indices must stay dense after the collapse"


@pytest_live
def test_citation_producers_stay_in_lockstep(live_conn):
    """The REST sources list, the SITREP prompt and the consistency evidence
    each number independently; a collapse applied to one and not the others
    silently repoints every [N] above the first duplicate."""
    from api import queries
    from pipeline.consistency import fetch_hotspot_evidence
    from pipeline.llm_verifier import LLMRepository

    hid, alpha, bravo = _seed_hotspot_with_duplicate_article(live_conn)

    rest = queries.fetch_hotspot_events(live_conn, hid)
    cited = [r for r in rest if r["citation_index"] is not None]
    articles = LLMRepository(live_conn).fetch_hotspot_articles(hid)
    evidence = fetch_hotspot_evidence(live_conn, hid)

    # The SITREP prompt list must be the same articles in the same order, or
    # the model's [N] numbering does not address the REST sources list.
    assert [a["url"] for a in articles] == [r["url"] for r in cited] == [bravo, alpha]

    # Two distinct domains, so the evidence per-domain dedupe keeps both rows
    # and every citation_index it reports must match the REST list exactly.
    index_by_event = {r["event_id"]: r["citation_index"] for r in cited}
    assert len(evidence) == 2
    for item in evidence:
        assert item["event_id"] in index_by_event, \
            "evidence references a row the sources list dropped"
        assert item["citation_index"] == index_by_event[item["event_id"]]
