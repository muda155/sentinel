"""FR-25: GDELT ingestion writes real headlines into events.title."""
import pandas as pd

from pipeline.ingestion import GDELT2Ingestor


def _gdelt_df() -> pd.DataFrame:
    return pd.DataFrame([{
        "GlobalEventID": 525252, "SQLDATE": 20260727, "EventRootCode": 19,
        "EventCode": "190", "Actor1Name": "SOUTH KOREAN", "Actor2Name": "RUSSIA",
        "GoldsteinScale": -8.0, "AvgTone": -5.2, "NumSources": 4,
        "ActionGeo_Lat": 37.5, "ActionGeo_Long": 127.0, "ActionGeo_Type": 3,
        "ActionGeo_CountryCode": "KS", "SOURCEURL": "https://example.com/kr",
    }])


_HEADLINE = "South Korea closely monitoring reported troop movements"

# Index of each field inside the tuple _augment_records builds.
_TITLE = 7
_ACTOR1 = 13


def test_augment_records_uses_headline_when_url_is_mapped():
    ingestor = GDELT2Ingestor()
    records = list(GDELT2Ingestor._build_event_records(_gdelt_df()))
    rows = ingestor._augment_records(
        records, {}, headlines={"https://example.com/kr": _HEADLINE}
    )
    assert rows[0][_TITLE] == _HEADLINE
    assert rows[0][_ACTOR1] == "SOUTH KOREAN"


def test_augment_records_falls_back_to_actor_name_when_url_missing():
    ingestor = GDELT2Ingestor()
    records = list(GDELT2Ingestor._build_event_records(_gdelt_df()))
    rows = ingestor._augment_records(
        records, {}, headlines={"https://example.com/other": _HEADLINE}
    )
    assert rows[0][_TITLE] == "SOUTH KOREAN"
    assert rows[0][_ACTOR1] == "SOUTH KOREAN"


def test_augment_records_defaults_to_instance_map():
    ingestor = GDELT2Ingestor()
    ingestor.latest_headlines = {"https://example.com/kr": _HEADLINE}
    records = list(GDELT2Ingestor._build_event_records(_gdelt_df()))
    assert ingestor._augment_records(records, {})[0][_TITLE] == _HEADLINE


def test_augment_records_without_any_map_preserves_pre_m7_behaviour():
    ingestor = GDELT2Ingestor()
    records = list(GDELT2Ingestor._build_event_records(_gdelt_df()))
    rows = ingestor._augment_records(records, {})
    assert rows[0][_TITLE] == "SOUTH KOREAN"


def test_run_once_populates_headline_map(monkeypatch):
    ingestor = GDELT2Ingestor()
    monkeypatch.setattr(
        GDELT2Ingestor, "fetch_latest_existing_url",
        lambda self: "http://data.gdeltproject.org/gdeltv2/20260727051500.export.CSV.zip",
    )
    monkeypatch.setattr(GDELT2Ingestor, "download_csv", lambda self, url: _gdelt_df())
    monkeypatch.setattr(
        "pipeline.ingestion.fetch_headlines",
        lambda url: {"https://example.com/kr": _HEADLINE},
    )
    ingestor.run_once()
    assert ingestor.latest_headlines == {"https://example.com/kr": _HEADLINE}


def test_run_once_skips_gkg_when_disabled(monkeypatch):
    monkeypatch.setenv("SENTINEL_GKG_ENABLED", "false")
    ingestor = GDELT2Ingestor()
    monkeypatch.setattr(
        GDELT2Ingestor, "fetch_latest_existing_url",
        lambda self: "http://data.gdeltproject.org/gdeltv2/20260727051500.export.CSV.zip",
    )
    monkeypatch.setattr(GDELT2Ingestor, "download_csv", lambda self, url: _gdelt_df())

    def boom(url):
        raise AssertionError("GKG must not be fetched when disabled")

    monkeypatch.setattr("pipeline.ingestion.fetch_headlines", boom)
    ingestor.run_once()
    assert ingestor.latest_headlines == {}


def test_insert_persists_headline_title_and_actor_name(live_conn):
    ingestor = GDELT2Ingestor()
    inserted = ingestor.insert_to_db(
        _gdelt_df(), live_conn, headlines={"https://example.com/kr": _HEADLINE}
    )
    assert inserted == 1
    with live_conn.cursor() as cur:
        cur.execute(
            """SELECT title, actor1_name FROM events
               WHERE source_system='GDELT' AND external_event_id='525252'"""
        )
        row = cur.fetchone()
    assert row == (_HEADLINE, "SOUTH KOREAN")
