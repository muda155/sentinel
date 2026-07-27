"""FR-21: ingestion persists the analytic fields it downloads."""
import pandas as pd

from pipeline.ingestion import GDELT2Ingestor


def _gdelt_df() -> pd.DataFrame:
    return pd.DataFrame([{
        "GlobalEventID": 424242, "SQLDATE": 20260726, "EventRootCode": 19,
        "EventCode": "190", "Actor1Name": "MILITARY", "Actor2Name": "REBELS",
        "GoldsteinScale": -8.0, "AvgTone": -5.2, "NumSources": 12,
        "ActionGeo_Lat": 31.5, "ActionGeo_Long": 34.45, "ActionGeo_Type": 3,
        "ActionGeo_CountryCode": "IS", "SOURCEURL": "https://example.com/a",
    }])


def test_build_event_records_carries_enrichment_fields():
    records = list(GDELT2Ingestor._build_event_records(_gdelt_df()))
    assert len(records) == 1
    rec = records[0]
    assert len(rec) == 13
    assert rec[9] == "REBELS"          # actor2_name
    assert rec[10] == -8.0             # goldstein_scale
    assert rec[11] == -5.2             # avg_tone
    assert rec[12] == 12               # num_sources


def test_build_event_records_tolerates_missing_enrichment():
    df = _gdelt_df().drop(columns=["Actor2Name", "GoldsteinScale", "AvgTone", "NumSources"])
    rec = list(GDELT2Ingestor._build_event_records(df))[0]
    assert rec[9] is None and rec[10] is None and rec[11] is None and rec[12] is None


def test_gdelt_insert_persists_enrichment(live_conn):
    ingestor = GDELT2Ingestor()
    inserted = ingestor.insert_to_db(_gdelt_df(), live_conn)
    assert inserted == 1
    with live_conn.cursor() as cur:
        cur.execute(
            """SELECT actor1_name, actor2_name, goldstein_scale, avg_tone, num_sources
               FROM events WHERE source_system='GDELT' AND external_event_id='424242'"""
        )
        row = cur.fetchone()
    assert row == ("MILITARY", "REBELS", -8.0, -5.2, 12)
