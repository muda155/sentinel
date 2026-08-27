"""api/cache.py - shared Redis client with failure memoization."""
import time

from api import cache


def _dead_redis(monkeypatch, calls):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6399")
    monkeypatch.setattr(cache, "_client", None)
    monkeypatch.setattr(cache, "_last_failure", 0.0)

    def _fail(*a, **k):
        calls["attempts"] += 1
        raise RuntimeError("redis down")

    monkeypatch.setattr("redis.from_url", _fail)


def test_redis_client_records_a_failed_attempt_for_the_cooldown(monkeypatch):
    calls = {"attempts": 0}
    _dead_redis(monkeypatch, calls)
    assert cache.redis_client() is None
    # the failure is remembered so the next call skips the connect attempt
    assert cache._last_failure > 0
    assert calls["attempts"] == 1


def test_redis_client_skips_reconnect_inside_the_cooldown(monkeypatch):
    calls = {"attempts": 0}
    _dead_redis(monkeypatch, calls)
    monkeypatch.setattr(cache, "_last_failure", time.monotonic() - 1)
    assert cache.redis_client() is None
    # the cooldown short-circuits before from_url is ever called again
    assert calls["attempts"] == 0


def test_redis_client_retries_once_the_cooldown_expires(monkeypatch):
    calls = {"attempts": 0}
    _dead_redis(monkeypatch, calls)
    cache.redis_client()
    monkeypatch.setattr(cache, "_last_failure", 0.0)  # cooldown expired
    cache.redis_client()
    assert calls["attempts"] == 2
