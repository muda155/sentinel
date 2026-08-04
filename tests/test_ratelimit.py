import time

from starlette.datastructures import Headers
from starlette.requests import Request

from api import ratelimit
from api.ratelimit import TokenBucket


def test_bucket_allows_then_blocks():
    b = TokenBucket(rate_per_min=2)
    assert b.allow("client-a")
    assert b.allow("client-a")
    assert not b.allow("client-a")          # 3rd within the window -> blocked
    assert b.allow("client-b")              # independent client


def test_bucket_refills_over_time():
    b = TokenBucket(rate_per_min=60)         # 1 token/sec
    assert b.allow("c")
    for _ in range(59):
        b.allow("c")
    assert not b.allow("c")
    time.sleep(1.1)
    assert b.allow("c")


def _request(client_host: str, xff: str | None) -> Request:
    headers = Headers({"x-forwarded-for": xff}) if xff else Headers({})
    scope = {"type": "http", "client": (client_host, 12345), "headers": headers.raw}
    return Request(scope)


def test_client_ip_ignores_xff_for_untrusted_direct_peer():
    # A spoofable X-Forwarded-For must never be trusted from an arbitrary peer.
    ratelimit._TRUSTED_PROXIES = frozenset({"10.0.0.2"})
    assert ratelimit._client_ip(_request("203.0.113.7", "6.6.6.6")) == "203.0.113.7"


def test_client_ip_uses_last_xff_entry_for_trusted_proxy():
    ratelimit._TRUSTED_PROXIES = frozenset({"10.0.0.2"})
    # The trusted proxy appends the original client IP; the last entry is what
    # it actually saw (earlier entries may be client-forged).
    assert ratelimit._client_ip(_request("10.0.0.2", "6.6.6.6, 203.0.113.7")) == "203.0.113.7"


def test_client_ip_falls_back_to_direct_peer_without_xff():
    ratelimit._TRUSTED_PROXIES = frozenset({"10.0.0.2"})
    assert ratelimit._client_ip(_request("10.0.0.2", None)) == "10.0.0.2"
