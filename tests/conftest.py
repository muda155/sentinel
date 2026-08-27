"""Shared pytest fixtures for the Sentinel test suite."""

from __future__ import annotations

import os

import pandas as pd
import psycopg2
import pytest


@pytest.fixture(autouse=True)
def _disable_network_backends(monkeypatch, request):
    """Disable GKG and relevance by default; tests opt in via markers."""
    if not request.node.get_closest_marker("gkg"):
        monkeypatch.setenv("SENTINEL_GKG_ENABLED", "false")
    if not request.node.get_closest_marker("relevance"):
        monkeypatch.setenv("SENTINEL_RELEVANCE_ENABLED", "false")


@pytest.fixture(autouse=True)
def _reset_rate_limit_buckets():
    """Give every test its own rate-limit buckets.

    The buckets in api.ratelimit are module singletons keyed on client IP, and
    every TestClient request presents the same key, so one budget is shared by
    the entire session. The auth bucket is only 10 tokens: once the suite makes
    an 11th /auth/login, some unrelated test gets a 429 instead of the status it
    asserts, and which test loses depends on how fast the runner is (tokens
    refill at 1 per 6s, so CI fails where a slow dev machine passes).
    """
    from api import ratelimit

    ratelimit._bucket = ratelimit.TokenBucket()
    ratelimit._auth_bucket = ratelimit.TokenBucket(rate_per_min=ratelimit.AUTH_RATE_PER_MIN)
    ratelimit._report_bucket = ratelimit.TokenBucket(rate_per_min=ratelimit.REPORT_RATE_PER_MIN)
    ratelimit._translate_bucket = ratelimit.TokenBucket(
        rate_per_min=ratelimit.TRANSLATE_RATE_PER_MIN)
    yield


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


@pytest.fixture
def live_conn():
    """A real psycopg2 connection for integration tests.

    Skips unless SENTINEL_TEST_DB is set to a libpq DSN, e.g.:
        SENTINEL_TEST_DB="host=127.0.0.1 port=5433 dbname=sentinel \
            user=sentinel_user password=sentinel_pass"
    The connection is rolled back at teardown so tests never persist data.
    """
    dsn = os.getenv("SENTINEL_TEST_DB")
    if not dsn:
        pytest.skip("SENTINEL_TEST_DB not set; skipping live-DB integration test")
    conn = psycopg2.connect(dsn)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()