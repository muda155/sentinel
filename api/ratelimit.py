from __future__ import annotations

import os
import threading
import time

from fastapi import HTTPException, Request
from starlette.status import HTTP_429_TOO_MANY_REQUESTS


class TokenBucket:
    """Per-client token-bucket rate limiter.

    Each client key gets a bucket of up to ``capacity`` tokens (defaults to
    *rate_per_min*).  Tokens refill at *rate_per_min* / 60 per second, computed
    on access so no background timer is needed.
    """

    def __init__(self, rate_per_min: int = 60) -> None:
        self._rate_per_sec = rate_per_min / 60.0
        self._capacity = rate_per_min
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=self._capacity, last=now)
                self._buckets[key] = bucket

            elapsed = now - bucket.last
            bucket.tokens = min(self._capacity, bucket.tokens + elapsed * self._rate_per_sec)
            bucket.last = now

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True
            return False


class _Bucket:
    __slots__ = ("tokens", "last")

    def __init__(self, tokens: float, last: float) -> None:
        self.tokens = tokens
        self.last = last


# --- FastAPI dependencies ------------------------------------------------

_bucket = TokenBucket()

# Comma-separated direct peers trusted to supply a real client IP in
# X-Forwarded-For (the Compose reverse proxy). When empty, rate limits key on
# the direct socket peer, which collapses to a single shared bucket for every
# user once a NAT or proxy sits in front.
_TRUSTED_PROXIES = frozenset(
    p.strip() for p in os.getenv("SENTINEL_TRUSTED_PROXIES", "").split(",") if p.strip()
)


def _client_ip(request: Request) -> str:
    """The address to rate-limit on, honoring a trusted proxy's X-Forwarded-For.

    X-Forwarded-For is appended by each hop and is spoofable by the immediate
    client, so only the LAST entry (added by the proxy we talk to) is used, and
    only when the direct peer is in SENTINEL_TRUSTED_PROXIES. This stops every
    user behind the Compose proxy from sharing one bucket.
    """
    direct = request.client.host if request.client else "unknown"
    if direct in _TRUSTED_PROXIES:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # The proxy appends the original client IP; the last entry is the
            # one it actually saw, not one the client may have forged.
            return forwarded.strip().split(",")[-1].strip() or direct
    return direct


def _rate_limit_client(request: Request) -> None:
    """Dependency that raises HTTP 429 when the client has exhausted tokens."""
    client_key = _client_ip(request)
    if not _bucket.allow(client_key):
        raise HTTPException(status_code=HTTP_429_TOO_MANY_REQUESTS,
                            detail="Rate limit exceeded. Try again later.")


limit_events = _rate_limit_client
limit_hotspots = _rate_limit_client


# Auth gets its own, much smaller bucket. Putting login on the shared bucket
# would let a login attempt spend the budget the dashboard needs, and 60/min of
# password guesses per IP is not a throttle.
AUTH_RATE_PER_MIN = 10

_auth_bucket = TokenBucket(rate_per_min=AUTH_RATE_PER_MIN)


def limit_auth(request: Request) -> None:
    """Stricter per-IP limit for credential endpoints."""
    client_key = _client_ip(request)
    if not _auth_bucket.allow(client_key):
        raise HTTPException(status_code=HTTP_429_TOO_MANY_REQUESTS,
                            detail="Too many attempts. Try again later.")
