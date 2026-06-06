"""Golden-dataset regression tests for GDELT ingestion (R7).

Locks the CAMEO filter behavior and the schema-validation contract so an
unintended change to filtering or column requirements fails CI loudly.
"""

from __future__ import annotations

import pandas as pd
import pytest

from pipeline.ingestion import GDELT2Ingestor, GDELTColumnSchema, SchemaError


def test_golden_military_filter_row_count(synthetic_gdelt_df: pd.DataFrame) -> None:
    ingestor = GDELT2Ingestor()
    filtered = ingestor.filter_military(synthetic_gdelt_df)
    # Exactly the 3 rows with EventRootCode in 14..19 survive (codes 14, 18, 19).
    assert len(filtered) == 3
    assert sorted(filtered["EventRootCode"].tolist()) == [14, 18, 19]


def test_golden_schema_validation_passes_for_complete_frame(
    synthetic_gdelt_df: pd.DataFrame,
) -> None:
    # Should not raise: the golden frame has every required column.
    GDELTColumnSchema.validate(synthetic_gdelt_df)


def test_golden_schema_validation_raises_on_missing_column(
    synthetic_gdelt_df: pd.DataFrame,
) -> None:
    broken = synthetic_gdelt_df.drop(columns=["EventRootCode"])
    with pytest.raises(SchemaError):
        GDELTColumnSchema.validate(broken)