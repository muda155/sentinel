from __future__ import annotations

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


def _rate_limit_client(request: Request) -> None:
    """Dependency that raises HTTP 429 when the client has exhausted tokens."""
    client_key = request.client.host if request.client else "unknown"
    if not _bucket.allow(client_key):
        raise HTTPException(status_code=HTTP_429_TOO_MANY_REQUESTS,
                            detail="Rate limit exceeded. Try again later.")


limit_events = _rate_limit_client
limit_hotspots = _rate_limit_client
