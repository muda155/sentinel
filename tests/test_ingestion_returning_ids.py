import pandas as pd

from pipeline.ingestion import GDELT2Ingestor


def test_augment_records_matches_legacy_columns():
    # _augment_records must yield 18-field tuples (matches the INSERT template
    # including geo_precision at index 12 and enrichment fields at 13-17)
    ing = GDELT2Ingestor()
    records = [(123, pd.Timestamp("2026-06-01", tz="UTC"), "190", "IL",
               "https://x.example/a", "ACTOR", 34.0, 31.0, None,
               None, None, None, None)]
    out = ing._augment_records(records, {"https://x.example/a": None})
    assert len(out) == 1
    assert len(out[0]) == 18
    assert out[0][0] == "GDELT"
    assert out[0][1] == 123          # gdelt_global_event_id
    assert out[0][2] == "123"        # external_event_id
