"""Thin Redis Streams wrapper: publish, consumer-group read, ack, stale-claim.

JSON-encodes the message body under a single Redis field 'data' so payloads
keep their Python types (lists/numbers) across the wire.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import redis

from api.metrics import METRICS

logger = logging.getLogger("sentinel.streams")


class UndecodableMessage(ValueError):
    """A stream entry whose body is not the JSON `data` shape this bus writes."""


class StreamBus:
    def __init__(
        self,
        client: redis.Redis | None = None,
        *,
        block_ms: int | None = None,
        batch: int | None = None,
        maxlen: int | None = None,
    ) -> None:
        self._r = client or redis.Redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379")
        )
        self._block_ms = block_ms if block_ms is not None else int(os.getenv("SENTINEL_STREAM_BLOCK_MS", "5000"))
        self._batch = batch if batch is not None else int(os.getenv("SENTINEL_STREAM_BATCH", "10"))
        self._maxlen = maxlen if maxlen is not None else int(os.getenv("SENTINEL_STREAM_MAXLEN", "100000"))

    @staticmethod
    def _decode(fields: dict) -> dict[str, Any]:
        raw = fields.get(b"data") or fields.get("data")
        if isinstance(raw, bytes):
            raw = raw.decode()
        if not isinstance(raw, str):
            raise UndecodableMessage("entry has no 'data' field")
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError) as error:
            raise UndecodableMessage(f"'data' is not valid JSON: {error}") from error

    def _decode_entries(self, entries, stream: str, group: str) -> list[tuple[str, dict]]:
        """Decode raw (id, fields) pairs, dropping any entry that cannot be read.

        Decoding happens here, before the worker loop reaches per-message
        handling, so an undecodable entry used to raise straight out of read()
        and kill the process — and kill it again on every restart, because the
        entry stayed in the stream. It is acked rather than left pending:
        a message that cannot be parsed can never be processed, and leaving it
        would only have claim_stale rediscover it forever. Losing one message
        beats an unattended crashloop that names no id.
        """
        out: list[tuple[str, dict]] = []
        for mid, fields in entries:
            mid = mid.decode() if isinstance(mid, bytes) else mid
            try:
                out.append((mid, self._decode(fields)))
            except UndecodableMessage as error:
                METRICS.inc("stream_undecodable_total")
                logger.error("dropping undecodable message %s on %s: %s",
                             mid, stream, error)
                self.ack(stream, group, mid)
        return out

    def ensure_group(self, stream: str, group: str) -> None:
        try:
            self._r.xgroup_create(stream, group, id="0", mkstream=True)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def publish(self, stream: str, payload: dict[str, Any]) -> str:
        mid = self._r.xadd(
            stream, {"data": json.dumps(payload)}, maxlen=self._maxlen, approximate=True
        )
        return mid.decode() if isinstance(mid, bytes) else mid

    def read(self, stream: str, group: str, consumer: str) -> list[tuple[str, dict]]:
        try:
            resp = self._r.xreadgroup(
                group, consumer, {stream: ">"}, count=self._batch, block=self._block_ms
            )
        except redis.exceptions.TimeoutError:
            return []
        return self._decode_entries(self._entries(resp), stream, group)

    def claim_stale(self, stream: str, group: str, consumer: str, *, min_idle_ms: int | None = None) -> list[tuple[str, dict]]:
        idle = min_idle_ms if min_idle_ms is not None else int(os.getenv("SENTINEL_STALE_MS", "7200000"))
        # XAUTOCLAIM reassigns messages idle longer than `idle` to this consumer.
        _cursor, msgs, _deleted = self._r.xautoclaim(
            stream, group, consumer, min_idle_time=idle, start_id="0-0", count=self._batch
        )
        return self._decode_entries(msgs, stream, group)

    def ack(self, stream: str, group: str, msg_id: str) -> None:
        self._r.xack(stream, group, msg_id)

    def pending_count(self, stream: str, group: str) -> int:
        info = self._r.xpending(stream, group)
        return int(info["pending"]) if isinstance(info, dict) else int(info[0])

    @staticmethod
    def _entries(resp):
        """Flatten xreadgroup's [(stream, [(id, fields), ...]), ...] response."""
        for _stream, entries in resp or []:
            yield from entries
