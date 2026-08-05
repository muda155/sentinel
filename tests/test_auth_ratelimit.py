import os

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.ratelimit import AUTH_RATE_PER_MIN, TokenBucket


def test_auth_bucket_is_not_the_shared_api_bucket():
    """A stricter auth bucket must not spend the 60/min budget that /hotspots,
    /events, /search and /grid_cells already share — logging in would then
    throttle the dashboard the user is logging in to."""
    from api import ratelimit

    assert ratelimit._auth_bucket is not ratelimit._bucket
    assert AUTH_RATE_PER_MIN < 60


def test_auth_bucket_exhausts_and_rejects():
    bucket = TokenBucket(rate_per_min=AUTH_RATE_PER_MIN)
    allowed = sum(1 for _ in range(AUTH_RATE_PER_MIN + 5) if bucket.allow("1.2.3.4"))
    assert allowed == AUTH_RATE_PER_MIN


@pytest.mark.skipif(
    not os.getenv("SENTINEL_TEST_DB"), reason="needs live DB"
)
def test_login_429s_after_the_auth_budget(monkeypatch):
    from api import ratelimit

    monkeypatch.setattr(ratelimit, "_auth_bucket", TokenBucket(rate_per_min=AUTH_RATE_PER_MIN))
    c = TestClient(create_app())
    codes = [
        c.post("/auth/login", json={"username": "nobody", "password": "wrong"}).status_code
        for _ in range(AUTH_RATE_PER_MIN + 2)
    ]
    assert 429 in codes, codes
    # The limiter must run BEFORE the DB lookup, or the throttle still costs a
    # pooled connection per guess.
    assert codes[-1] == 429
