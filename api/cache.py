"""Shared Redis client for cached, user-triggered endpoints.

One client (and one pool) per process, not a fresh pool per request. The short
connect timeout stops an unreachable REDIS_URL from pinning a threadpool worker
for the OS default, which can be minutes."""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger("sentinel.api.cache")

_client = None


def redis_client():
    global _client
    if _client is not None:
        return _client
    try:
        import redis as redis_lib
    except ImportError:
        return None
    try:
        client = redis_lib.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379"),
            socket_connect_timeout=1, socket_timeout=1,
        )
        client.ping()
    except Exception:
        return None
    _client = client
    return _client


def cache_get_json(key: str) -> dict | None:
    client = redis_client()
    if client is None:
        return None
    try:
        hit = client.get(key)
    except Exception:
        logger.warning("cache read failed", exc_info=True)
        return None
    if not hit:
        return None
    try:
        return json.loads(hit)
    except ValueError:
        logger.warning("cache held unparseable JSON for %s", key)
        return None


def cache_setex_json(key: str, ttl_s: int, payload: dict) -> None:
    client = redis_client()
    if client is None:
        return
    try:
        client.setex(key, ttl_s, json.dumps(payload))
    except Exception:
        logger.warning("cache write failed", exc_info=True)
