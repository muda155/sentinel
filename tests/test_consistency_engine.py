"""Engine integration: persistence, graceful failure (FR-22). Uses live DB."""
import pytest

from pipeline.consistency import run_consistency_engine
from pipeline.nli import NLIUnavailable


class FakeJudge:
    def classify_pairs(self, pairs):
        return [("supports", 0.9) for _ in pairs]


class BrokenJudge:
    def classify_pairs(self, pairs):
        raise NLIUnavailable("no model in CI")


def _fake_llm(prompt):
    return ('{"claims": [{"text": "Clashes occurred in the area.", '
            '"source_indices": [1]}]}', "fake-model")


@pytest.fixture
def seeded_hotspot(live_conn):
    """A hotspot with two linked url-bearing events from two domains."""
    with live_conn.cursor() as cur:
        cur.execute(
            """INSERT INTO hotspots (centroid_geom, radius_km, start_window,
                   end_window, event_count, unique_sources)
               VALUES (ST_SetSRID(ST_MakePoint(34.45, 31.5), 4326), 5.0,
                       now(), now(), 2, 2)
               RETURNING hotspot_id"""
        )
        hotspot_id = cur.fetchone()[0]
        for i, domain in enumerate(("m6a.example", "m6b.example"), start=1):
            url = f"https://{domain}/art{i}"
            cur.execute("SELECT register_source(%s, %s)", (url, None))
            source_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO events (source_system, external_event_id, event_date,
                       cameo_code, url, title, source_id, point_geom, notes)
                   VALUES ('ACLED', %s, now(), 'armed_conflict', %s, 'seed', %s,
                           ST_SetSRID(ST_MakePoint(34.45, 31.5), 4326),
                           'Clashes were reported in the area.')
                   RETURNING event_id""",
                (f"M6-ENG-{i}", url, source_id),
            )
            event_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO event_hotspot (event_id, hotspot_id) VALUES (%s, %s)",
                (event_id, hotspot_id),
            )
    return hotspot_id


def test_engine_persists_claims_and_score(live_conn, seeded_hotspot):
    result = run_consistency_engine(
        live_conn, seeded_hotspot, judge=FakeJudge(), llm=_fake_llm,
    )
    assert result is not None
    assert result.score is not None
    with live_conn.cursor() as cur:
        cur.execute("SELECT claim_text, status FROM claims WHERE hotspot_id = %s",
                    (seeded_hotspot,))
        rows = cur.fetchall()
        assert rows == [("Clashes occurred in the area.", "uncorroborated")]
        cur.execute("SELECT count(*) FROM claim_evidence ce JOIN claims c "
                    "ON c.claim_id = ce.claim_id WHERE c.hotspot_id = %s",
                    (seeded_hotspot,))
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT consistency_score FROM hotspots WHERE hotspot_id = %s",
                    (seeded_hotspot,))
        assert cur.fetchone()[0] == pytest.approx(result.score)


def test_engine_rerun_replaces_claims(live_conn, seeded_hotspot):
    run_consistency_engine(live_conn, seeded_hotspot, judge=FakeJudge(), llm=_fake_llm)
    run_consistency_engine(live_conn, seeded_hotspot, judge=FakeJudge(), llm=_fake_llm)
    with live_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM claims WHERE hotspot_id = %s", (seeded_hotspot,))
        assert cur.fetchone()[0] == 1  # replaced, not duplicated


def test_engine_broken_judge_returns_none_and_leaves_null(live_conn, seeded_hotspot):
    result = run_consistency_engine(
        live_conn, seeded_hotspot, judge=BrokenJudge(), llm=_fake_llm,
    )
    assert result is None
    with live_conn.cursor() as cur:
        cur.execute("SELECT consistency_score FROM hotspots WHERE hotspot_id = %s",
                    (seeded_hotspot,))
        assert cur.fetchone()[0] is None


def test_engine_no_evidence_returns_none(live_conn):
    with live_conn.cursor() as cur:
        cur.execute(
            """INSERT INTO hotspots (centroid_geom, radius_km, start_window,
                   end_window, event_count, unique_sources)
               VALUES (ST_SetSRID(ST_MakePoint(0, 0), 4326), 5.0, now(), now(), 0, 0)
               RETURNING hotspot_id"""
        )
        empty_id = cur.fetchone()[0]
    assert run_consistency_engine(live_conn, empty_id, judge=FakeJudge(),
                                  llm=_fake_llm) is None


def test_fetch_evidence_one_row_per_domain_keeps_indices(live_conn):
    from pipeline.consistency import fetch_hotspot_evidence

    with live_conn.cursor() as cur:
        cur.execute(
            """INSERT INTO hotspots (centroid_geom, radius_km, start_window,
                   end_window, event_count, unique_sources)
               VALUES (ST_SetSRID(ST_MakePoint(34.45, 31.5), 4326), 5.0,
                       now(), now(), 3, 2)
               RETURNING hotspot_id"""
        )
        hid = cur.fetchone()[0]
        # Insert order -> event_id ASC; evidence orders event_id DESC, so
        # citation order is e3, e2, e1. Domains: dup, dup, uniq.
        for i, domain in enumerate(("m6dup.example", "m6dup.example", "m6uniq.example"), start=1):
            url = f"https://{domain}/dedupe{i}"
            cur.execute("SELECT register_source(%s, %s)", (url, None))
            source_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO events (source_system, external_event_id, event_date,
                       cameo_code, url, title, source_id, point_geom, notes)
                   VALUES ('ACLED', %s, date_trunc('hour', now()), 'armed_conflict',
                           %s, 'seed', %s,
                           ST_SetSRID(ST_MakePoint(34.45, 31.5), 4326), 'Clash reported.')
                   RETURNING event_id""",
                (f"M6-DEDUPE-{i}", url, source_id),
            )
            event_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO event_hotspot (event_id, hotspot_id) VALUES (%s, %s)",
                (event_id, hid),
            )

    evidence = fetch_hotspot_evidence(live_conn, hid)
    # One row per domain; the duplicate domain keeps its FIRST (most recent)
    # row and its ORIGINAL citation index so [N] still maps to the FR-16 list.
    assert [(e["domain"], e["citation_index"]) for e in evidence] == [
        ("m6uniq.example", 1),
        ("m6dup.example", 2),
    ]
