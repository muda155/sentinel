"""Shared pytest fixtures for the Sentinel test suite."""

from __future__ import annotations

import pandas as pd
import pytest


@pytest.fixture
def synthetic_gdelt_df() -> pd.DataFrame:
    """A valid GDELT 2.0 frame with all required columns.

    Contains 6 rows: 3 with military CAMEO root codes (14, 18, 19) that
    must survive filter_military, and 3 with non-military codes (1, 4, 10)
    that must be dropped. Used as the golden dataset for FR-2 / R7.
    """
    return pd.DataFrame(
        {
            "GLOBALEVENTID": [1, 2, 3, 4, 5, 6],
            "SQLDATE": [20260601] * 6,
            "EventRootCode": [14, 18, 19, 1, 4, 10],
            "EventCode": ["140", "180", "190", "010", "040", "100"],
            "Actor1Name": ["A", "B", "C", "D", "E", "F"],
            "ActionGeo_Lat": [32.0, 32.1, 31.9, 10.0, 11.0, 12.0],
            "ActionGeo_Long": [35.0, 35.1, 34.9, 20.0, 21.0, 22.0],
            "SOURCEURL": [f"https://news{i}.example.com/a" for i in range(6)],
        }
    )